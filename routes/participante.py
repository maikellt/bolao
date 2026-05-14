"""
Rotas do participante — dashboard, ranking, histórico.
"""

from fastapi import APIRouter, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from auth import require_auth
from database import get_db
from services.pontuacao import calcular_ranking

router = APIRouter(tags=["participante"])
templates = Jinja2Templates(directory="templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, user: dict = Depends(require_auth)):
    user_id = int(user["sub"])
    with get_db() as conn:
        cotas = conn.execute(
            """SELECT c.*, b.nome AS bolao_nome, b.id AS bolao_id,
                      COALESCE(SUM(p.pontos_total), 0) AS total_pontos
               FROM cotas c
               JOIN boloes b ON c.bolao_id = b.id
               LEFT JOIN pontuacoes p ON p.cota_id = c.id
               WHERE c.user_id = ?
               GROUP BY c.id
               ORDER BY b.id, c.numero""",
            (user_id,),
        ).fetchall()

        boloes_ids = list({c["bolao_id"] for c in cotas})
        fases_abertas = []
        if boloes_ids:
            ph = ",".join(["?" for _ in boloes_ids])
            fases_abertas = conn.execute(
                f"SELECT * FROM fases WHERE bolao_id IN ({ph}) AND status = 'aberta' ORDER BY ordem",
                boloes_ids,
            ).fetchall()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "cotas": [dict(c) for c in cotas],
            "fases_abertas": [dict(f) for f in fases_abertas],
        },
    )


@router.get("/bolao/{bolao_id}/ranking", response_class=HTMLResponse)
async def ranking_page(
    request: Request,
    bolao_id: int,
    user: dict = Depends(require_auth),
):
    user_id = int(user["sub"])
    with get_db() as conn:
        acesso = conn.execute(
            "SELECT id FROM cotas WHERE bolao_id = ? AND user_id = ?",
            (bolao_id, user_id),
        ).fetchone()
        if not acesso:
            raise HTTPException(403, "Acesso negado")

        bolao = conn.execute("SELECT * FROM boloes WHERE id = ?", (bolao_id,)).fetchone()
        fases = conn.execute(
            "SELECT * FROM fases WHERE bolao_id = ? ORDER BY ordem", (bolao_id,)
        ).fetchall()

    ranking = calcular_ranking(bolao_id)

    return templates.TemplateResponse(
        "ranking.html",
        {
            "request": request,
            "user": user,
            "bolao": dict(bolao),
            "ranking": ranking,
            "fases": [dict(f) for f in fases],
            "user_id": user_id,
        },
    )


@router.get("/cota/{cota_id}/historico", response_class=HTMLResponse)
async def historico_cota(
    request: Request,
    cota_id: int,
    user: dict = Depends(require_auth),
):
    """Histórico de pontuação jogo a jogo de uma cota."""
    user_id = int(user["sub"])
    with get_db() as conn:
        # Cota pode ser de outro participante (visibilidade aberta)
        cota = conn.execute(
            """SELECT c.*, u.nome AS participante
               FROM cotas c JOIN users u ON c.user_id = u.id
               WHERE c.id = ?""",
            (cota_id,),
        ).fetchone()
        if not cota:
            raise HTTPException(404)

        # Verifica se o usuário pertence ao mesmo bolão
        acesso = conn.execute(
            "SELECT id FROM cotas WHERE bolao_id = ? AND user_id = ?",
            (cota["bolao_id"], user_id),
        ).fetchone()
        if not acesso:
            raise HTTPException(403)

        historico = conn.execute(
            """SELECT j.time_casa, j.time_fora, j.data_hora,
                      f.nome AS fase_nome, f.slug AS fase_slug,
                      p.gols_casa AS p_casa, p.gols_fora AS p_fora, p.classificado AS p_class,
                      r.gols_casa AS r_casa, r.gols_fora AS r_fora, r.classificado AS r_class,
                      pt.pontos_total, pt.tipo_acerto
               FROM jogos j
               JOIN fases f ON j.fase_id = f.id
               LEFT JOIN palpites p ON p.jogo_id = j.id AND p.cota_id = ?
               LEFT JOIN resultados r ON r.jogo_id = j.id
               LEFT JOIN pontuacoes pt ON pt.jogo_id = j.id AND pt.cota_id = ?
               WHERE j.bolao_id = ?
               ORDER BY j.data_hora""",
            (cota_id, cota_id, cota["bolao_id"]),
        ).fetchall()

        bolao = conn.execute(
            "SELECT * FROM boloes WHERE id = ?", (cota["bolao_id"],)
        ).fetchone()

        palpite_campeao = conn.execute(
            "SELECT * FROM palpites_campeao WHERE cota_id = ?", (cota_id,)
        ).fetchone()

    return templates.TemplateResponse(
        "historico.html",
        {
            "request": request,
            "user": user,
            "cota": dict(cota),
            "bolao": dict(bolao),
            "historico": [dict(h) for h in historico],
            "palpite_campeao": dict(palpite_campeao) if palpite_campeao else None,
        },
    )


@router.get("/api/simulador")
async def simulador(
    gols_casa: int,
    gols_fora: int,
    fase_slug: str,
    classificado: str = "",
    user: dict = Depends(require_auth),
):
    """Simulador de pontuação — não salva nenhum palpite."""
    from services.pontuacao import calcular_pontos_jogo, MULTIPLICADORES

    mult = MULTIPLICADORES.get(fase_slug, 1.0)
    is_mata_mata = fase_slug not in ("grupos",)

    # Simula resultado hipotético
    resultado = calcular_pontos_jogo(
        palpite_casa=gols_casa,
        palpite_fora=gols_fora,
        palpite_classificado=classificado or None,
        resultado_casa=gols_casa,  # se acertasse exatamente
        resultado_fora=gols_fora,
        resultado_classificado=classificado or None,
        multiplicador=mult,
        is_mata_mata=is_mata_mata,
    )
    return JSONResponse({
        "fase": fase_slug,
        "multiplicador": mult,
        "pontos_possiveis": resultado["pontos_total"],
        "tipo": resultado["tipo_acerto"],
    })
