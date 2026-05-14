"""
Rotas de palpites — envio, edição e visualização.
Regra crítica: bloqueio 4h antes do primeiro jogo do dia.
"""

from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from auth import require_auth
from database import get_db, get_write_db, increment_data_revision

router = APIRouter(prefix="/palpites", tags=["palpites"])
templates = Jinja2Templates(directory="templates")


def _get_bloqueio_dia(conn, bolao_id: int, data_str: str) -> datetime | None:
    """
    Retorna o horário de bloqueio para um determinado dia (4h antes do primeiro jogo).
    """
    # data_str no formato 'YYYY-MM-DD'
    jogos_dia = conn.execute(
        """SELECT MIN(data_hora) AS primeiro_jogo
           FROM jogos
           WHERE bolao_id = ?
             AND substr(data_hora, 1, 10) = ?""",
        (bolao_id, data_str),
    ).fetchone()

    if not jogos_dia or not jogos_dia["primeiro_jogo"]:
        return None

    primeiro = datetime.fromisoformat(jogos_dia["primeiro_jogo"].replace("Z", "+00:00"))
    if primeiro.tzinfo is None:
        primeiro = primeiro.replace(tzinfo=timezone.utc)
    return primeiro - timedelta(hours=4)


def _palpite_bloqueado(conn, jogo_id: int, bolao_id: int) -> bool:
    """Verifica se o palpite para este jogo está bloqueado."""
    jogo = conn.execute(
        "SELECT data_hora FROM jogos WHERE id = ?", (jogo_id,)
    ).fetchone()
    if not jogo:
        return True

    data_jogo = jogo["data_hora"][:10]  # YYYY-MM-DD
    bloqueio = _get_bloqueio_dia(conn, bolao_id, data_jogo)
    if not bloqueio:
        return True

    now = datetime.now(timezone.utc)
    return now >= bloqueio


@router.get("/bolao/{bolao_id}/fase/{fase_id}", response_class=HTMLResponse)
async def pagina_palpites(
    request: Request,
    bolao_id: int,
    fase_id: int,
    user: dict = Depends(require_auth),
):
    user_id = int(user["sub"])
    with get_db() as conn:
        # Verifica se usuário pertence ao bolão
        cotas = conn.execute(
            "SELECT * FROM cotas WHERE bolao_id = ? AND user_id = ?",
            (bolao_id, user_id),
        ).fetchall()
        if not cotas:
            raise HTTPException(403, "Você não possui cotas neste bolão")

        fase = conn.execute(
            "SELECT * FROM fases WHERE id = ? AND bolao_id = ?",
            (fase_id, bolao_id),
        ).fetchone()
        if not fase:
            raise HTTPException(404, "Fase não encontrada")

        jogos = conn.execute(
            "SELECT * FROM jogos WHERE fase_id = ? ORDER BY data_hora",
            (fase_id,),
        ).fetchall()

        bolao = conn.execute(
            "SELECT * FROM boloes WHERE id = ?", (bolao_id,)
        ).fetchone()

        # Palpites existentes para as cotas do usuário
        cota_ids = [c["id"] for c in cotas]
        palpites_existentes = {}
        if cota_ids:
            placeholders = ",".join(["?" for _ in cota_ids])
            rows = conn.execute(
                f"""SELECT * FROM palpites
                    WHERE cota_id IN ({placeholders})
                    AND jogo_id IN (SELECT id FROM jogos WHERE fase_id = ?)""",
                cota_ids + [fase_id],
            ).fetchall()
            for p in rows:
                key = f"{p['cota_id']}_{p['jogo_id']}"
                palpites_existentes[key] = dict(p)

        # Resultados já lançados
        jogo_ids = [j["id"] for j in jogos]
        resultados = {}
        if jogo_ids:
            ph = ",".join(["?" for _ in jogo_ids])
            res_rows = conn.execute(
                f"SELECT * FROM resultados WHERE jogo_id IN ({ph})", jogo_ids
            ).fetchall()
            for r in res_rows:
                resultados[r["jogo_id"]] = dict(r)

        # Calcula bloqueio por dia
        bloqueios_dia = {}
        for j in jogos:
            data = j["data_hora"][:10]
            if data not in bloqueios_dia:
                bl = _get_bloqueio_dia(conn, bolao_id, data)
                bloqueios_dia[data] = bl.isoformat() if bl else None

    now = datetime.now(timezone.utc).isoformat()
    return templates.TemplateResponse(
        "palpites.html",
        {
            "request": request,
            "user": user,
            "bolao": dict(bolao),
            "fase": dict(fase),
            "jogos": [dict(j) for j in jogos],
            "cotas": [dict(c) for c in cotas],
            "palpites": palpites_existentes,
            "resultados": resultados,
            "bloqueios_dia": bloqueios_dia,
            "now": now,
        },
    )


@router.post("/salvar")
async def salvar_palpite(
    request: Request,
    user: dict = Depends(require_auth),
):
    """Salva ou atualiza um palpite (JSON API)."""
    body = await request.json()
    cota_id = int(body.get("cota_id"))
    jogo_id = int(body.get("jogo_id"))
    gols_casa = int(body.get("gols_casa", 0))
    gols_fora = int(body.get("gols_fora", 0))
    classificado = body.get("classificado")

    user_id = int(user["sub"])

    with get_db() as conn:
        # Verifica posse da cota
        cota = conn.execute(
            "SELECT * FROM cotas WHERE id = ? AND user_id = ?",
            (cota_id, user_id),
        ).fetchone()
        if not cota:
            raise HTTPException(403, "Cota não pertence ao usuário")

        if not cota["pago"]:
            raise HTTPException(400, "Cota não está ativa (pagamento pendente)")

        # Busca o jogo e valida fase aberta
        jogo = conn.execute(
            """SELECT j.*, f.status AS fase_status, f.slug AS fase_slug
               FROM jogos j JOIN fases f ON j.fase_id = f.id
               WHERE j.id = ?""",
            (jogo_id,),
        ).fetchone()
        if not jogo:
            raise HTTPException(404, "Jogo não encontrado")

        if jogo["fase_status"] != "aberta":
            raise HTTPException(400, "Fase fechada para palpites")

        # Regra: campo classificado obrigatório no mata-mata
        is_mata_mata = jogo["fase_slug"] not in ("grupos",)
        if is_mata_mata and not classificado:
            raise HTTPException(
                400, "Campo 'classificado' obrigatório no mata-mata"
            )

        # Regra: bloqueio 4h antes do primeiro jogo do dia
        if _palpite_bloqueado(conn, jogo_id, cota["bolao_id"]):
            raise HTTPException(400, "Prazo de palpites encerrado para hoje")

    now = datetime.now(timezone.utc).isoformat()
    with get_write_db() as conn:
        conn.execute(
            """INSERT INTO palpites (cota_id, jogo_id, gols_casa, gols_fora, classificado, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cota_id, jogo_id) DO UPDATE SET
                   gols_casa=excluded.gols_casa,
                   gols_fora=excluded.gols_fora,
                   classificado=excluded.classificado,
                   updated_at=excluded.updated_at""",
            (cota_id, jogo_id, gols_casa, gols_fora, classificado, now, now),
        )

    increment_data_revision()
    return JSONResponse({"ok": True, "mensagem": "Palpite salvo com sucesso"})


@router.post("/campeao/salvar")
async def salvar_campeao(
    request: Request,
    user: dict = Depends(require_auth),
):
    """Salva o palpite do campeão da Copa."""
    body = await request.json()
    cota_id = int(body.get("cota_id"))
    time_campeao = body.get("time_campeao", "").strip()

    if not time_campeao:
        raise HTTPException(400, "Nome do time é obrigatório")

    user_id = int(user["sub"])

    with get_db() as conn:
        cota = conn.execute(
            "SELECT * FROM cotas WHERE id = ? AND user_id = ?",
            (cota_id, user_id),
        ).fetchone()
        if not cota:
            raise HTTPException(403, "Cota não pertence ao usuário")

        # Verifica se a primeira partida já iniciou
        primeiro_jogo = conn.execute(
            """SELECT MIN(data_hora) AS dt FROM jogos WHERE bolao_id = ?""",
            (cota["bolao_id"],),
        ).fetchone()

        if primeiro_jogo and primeiro_jogo["dt"]:
            dt = datetime.fromisoformat(primeiro_jogo["dt"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) >= dt:
                raise HTTPException(
                    400, "Palpite do campeão não pode ser alterado após o início do torneio"
                )

        # Verifica se já existe e não está bloqueado
        existente = conn.execute(
            "SELECT * FROM palpites_campeao WHERE cota_id = ?", (cota_id,)
        ).fetchone()
        if existente and existente["bloqueado"]:
            raise HTTPException(400, "Palpite do campeão está bloqueado")

    now = datetime.now(timezone.utc).isoformat()
    with get_write_db() as conn:
        conn.execute(
            """INSERT INTO palpites_campeao (cota_id, time_campeao, bloqueado, created_at)
               VALUES (?, ?, 0, ?)
               ON CONFLICT(cota_id) DO UPDATE SET
                   time_campeao=excluded.time_campeao""",
            (cota_id, time_campeao, now),
        )

    increment_data_revision()
    return JSONResponse({"ok": True})


@router.get("/todos/{bolao_id}/{fase_id}", response_class=JSONResponse)
async def palpites_todos(
    bolao_id: int,
    fase_id: int,
    user: dict = Depends(require_auth),
):
    """Retorna palpites de todas as cotas ativas (visibilidade aberta)."""
    with get_db() as conn:
        # Verifica se o usuário pertence ao bolão
        cota = conn.execute(
            "SELECT id FROM cotas WHERE bolao_id = ? AND user_id = ?",
            (bolao_id, int(user["sub"])),
        ).fetchone()
        if not cota:
            raise HTTPException(403, "Acesso negado")

        rows = conn.execute(
            """SELECT p.*, c.numero AS numero_cota, u.nome AS participante
               FROM palpites p
               JOIN cotas c ON p.cota_id = c.id
               JOIN users u ON c.user_id = u.id
               JOIN jogos j ON p.jogo_id = j.id
               WHERE j.fase_id = ? AND c.bolao_id = ?
               ORDER BY c.numero, j.data_hora""",
            (fase_id, bolao_id),
        ).fetchall()

    return [dict(r) for r in rows]
