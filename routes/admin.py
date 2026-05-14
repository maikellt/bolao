"""
Rotas do administrador — gerenciamento completo do bolão.
"""

import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth import require_admin
from database import get_db, get_write_db, increment_data_revision
from services.pontuacao import processar_pontuacao_jogo, calcular_ranking, calcular_premiacao
from services.email_service import (
    enviar_abertura_fase,
    enviar_resultado_lancado,
    enviar_confirmacao_pagamento,
)

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="templates")


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(request: Request, user: dict = Depends(require_admin)):
    with get_db() as conn:
        boloes = conn.execute("SELECT * FROM boloes ORDER BY id DESC").fetchall()
        total_users = conn.execute("SELECT COUNT(*) AS cnt FROM users WHERE is_admin = 0").fetchone()["cnt"]
        total_cotas = conn.execute("SELECT COUNT(*) AS cnt FROM cotas WHERE pago = 1").fetchone()["cnt"]

    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "user": user,
            "boloes": [dict(b) for b in boloes],
            "total_users": total_users,
            "total_cotas": total_cotas,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# BOLÃO
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/bolao/novo", response_class=HTMLResponse)
async def novo_bolao_page(request: Request, user: dict = Depends(require_admin)):
    return templates.TemplateResponse("admin/bolao_form.html", {"request": request, "user": user})


@router.post("/bolao/novo")
async def criar_bolao(
    request: Request,
    nome: str = Form(...),
    descricao: str = Form(""),
    valor_cota: float = Form(20.0),
    divisao_1: float = Form(40.0),
    divisao_2: float = Form(25.0),
    divisao_3: float = Form(15.0),
    divisao_4: float = Form(10.0),
    divisao_5: float = Form(10.0),
    user: dict = Depends(require_admin),
):
    now = datetime.now(timezone.utc).isoformat()
    with get_write_db() as conn:
        cur = conn.execute(
            """INSERT INTO boloes
               (nome, descricao, valor_cota, divisao_1, divisao_2, divisao_3, divisao_4, divisao_5, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (nome, descricao, valor_cota, divisao_1, divisao_2, divisao_3, divisao_4, divisao_5, now),
        )
        bolao_id = cur.lastrowid
        # Cria as fases padrão da Copa 2026
        fases_padrao = [
            ("Fase de Grupos", "grupos", 1, 1.0),
            ("Fase de 32", "fase32", 2, 1.5),
            ("Oitavas de Final", "oitavas", 3, 1.5),
            ("Quartas de Final", "quartas", 4, 2.0),
            ("Semifinal", "semifinal", 5, 3.0),
            ("Final", "final", 6, 4.0),
        ]
        for nome_fase, slug, ordem, mult in fases_padrao:
            conn.execute(
                """INSERT OR IGNORE INTO fases (bolao_id, nome, slug, ordem, multiplicador)
                   VALUES (?, ?, ?, ?, ?)""",
                (bolao_id, nome_fase, slug, ordem, mult),
            )

    increment_data_revision()
    return RedirectResponse(url=f"/admin/bolao/{bolao_id}", status_code=302)


@router.get("/bolao/{bolao_id}", response_class=HTMLResponse)
async def detalhe_bolao(
    request: Request,
    bolao_id: int,
    user: dict = Depends(require_admin),
):
    with get_db() as conn:
        bolao = conn.execute("SELECT * FROM boloes WHERE id = ?", (bolao_id,)).fetchone()
        if not bolao:
            raise HTTPException(404)

        fases = conn.execute(
            "SELECT * FROM fases WHERE bolao_id = ? ORDER BY ordem", (bolao_id,)
        ).fetchall()
        cotas = conn.execute(
            """SELECT c.*, u.nome AS participante, u.email
               FROM cotas c JOIN users u ON c.user_id = u.id
               WHERE c.bolao_id = ? ORDER BY c.numero""",
            (bolao_id,),
        ).fetchall()
        total_arrecadado = conn.execute(
            "SELECT COUNT(*) * ? AS total FROM cotas WHERE bolao_id = ? AND pago = 1",
            (bolao["valor_cota"], bolao_id),
        ).fetchone()["total"]

    return templates.TemplateResponse(
        "admin/bolao_detalhe.html",
        {
            "request": request,
            "user": user,
            "bolao": dict(bolao),
            "fases": [dict(f) for f in fases],
            "cotas": [dict(c) for c in cotas],
            "total_arrecadado": total_arrecadado or 0,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# CONVITES
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/bolao/{bolao_id}/convite")
async def gerar_convite(
    request: Request,
    bolao_id: int,
    email_destino: str = Form(""),
    dias_validade: int = Form(7),
    user: dict = Depends(require_admin),
):
    token = secrets.token_urlsafe(32)
    expira = (datetime.now(timezone.utc) + timedelta(days=dias_validade)).isoformat()
    now = datetime.now(timezone.utc).isoformat()

    with get_write_db() as conn:
        conn.execute(
            "INSERT INTO convites (bolao_id, token, email_destino, expira_em, created_at) VALUES (?, ?, ?, ?, ?)",
            (bolao_id, token, email_destino or None, expira, now),
        )
    increment_data_revision()

    base_url = str(request.base_url).rstrip("/")
    link = f"{base_url}/convite/{token}"
    return JSONResponse({"link": link, "token": token, "expira_em": expira})


# ──────────────────────────────────────────────────────────────────────────────
# COTAS — CONFIRMAÇÃO DE PAGAMENTO
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/cota/{cota_id}/confirmar-pagamento")
async def confirmar_pagamento(
    cota_id: int,
    user: dict = Depends(require_admin),
):
    with get_db() as conn:
        cota = conn.execute(
            """SELECT c.*, u.email, u.nome FROM cotas c
               JOIN users u ON c.user_id = u.id
               WHERE c.id = ?""",
            (cota_id,),
        ).fetchone()
    if not cota:
        raise HTTPException(404)

    with get_write_db() as conn:
        conn.execute("UPDATE cotas SET pago = 1 WHERE id = ?", (cota_id,))
    increment_data_revision()

    try:
        await enviar_confirmacao_pagamento(cota["email"], cota["nome"], cota["numero"])
    except Exception:
        pass

    return JSONResponse({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# FASES
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/fase/{fase_id}/status")
async def atualizar_status_fase(
    fase_id: int,
    request: Request,
    user: dict = Depends(require_admin),
):
    body = await request.json()
    novo_status = body.get("status")
    if novo_status not in ("aberta", "fechada", "nao_iniciada"):
        raise HTTPException(400, "Status inválido")

    with get_write_db() as conn:
        conn.execute("UPDATE fases SET status = ? WHERE id = ?", (novo_status, fase_id))
    increment_data_revision()

    if novo_status == "aberta":
        # Notifica participantes
        with get_db() as conn:
            fase = conn.execute("SELECT * FROM fases WHERE id = ?", (fase_id,)).fetchone()
            users_ativos = conn.execute(
                """SELECT DISTINCT u.email, u.nome
                   FROM cotas c JOIN users u ON c.user_id = u.id
                   WHERE c.bolao_id = ? AND c.pago = 1""",
                (fase["bolao_id"],),
            ).fetchall()

        for u in users_ativos:
            try:
                await enviar_abertura_fase(u["email"], u["nome"], fase["nome"], "")
            except Exception:
                pass

    return JSONResponse({"ok": True})


# ──────────────────────────────────────────────────────────────────────────────
# JOGOS
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/bolao/{bolao_id}/jogos", response_class=HTMLResponse)
async def jogos_page(
    request: Request,
    bolao_id: int,
    user: dict = Depends(require_admin),
):
    with get_db() as conn:
        bolao = conn.execute("SELECT * FROM boloes WHERE id = ?", (bolao_id,)).fetchone()
        fases = conn.execute(
            "SELECT * FROM fases WHERE bolao_id = ? ORDER BY ordem", (bolao_id,)
        ).fetchall()
        jogos = conn.execute(
            """SELECT j.*, f.nome AS fase_nome
               FROM jogos j JOIN fases f ON j.fase_id = f.id
               WHERE j.bolao_id = ? ORDER BY j.data_hora""",
            (bolao_id,),
        ).fetchall()
        resultados = conn.execute(
            """SELECT r.* FROM resultados r
               JOIN jogos j ON r.jogo_id = j.id
               WHERE j.bolao_id = ?""",
            (bolao_id,),
        ).fetchall()

    res_map = {r["jogo_id"]: dict(r) for r in resultados}

    return templates.TemplateResponse(
        "admin/jogos.html",
        {
            "request": request,
            "user": user,
            "bolao": dict(bolao),
            "fases": [dict(f) for f in fases],
            "jogos": [dict(j) for j in jogos],
            "resultados": res_map,
        },
    )


@router.post("/jogo/novo")
async def criar_jogo(
    request: Request,
    user: dict = Depends(require_admin),
):
    body = await request.json()
    bolao_id = int(body["bolao_id"])
    fase_id = int(body["fase_id"])
    time_casa = body["time_casa"].strip()
    time_fora = body["time_fora"].strip()
    data_hora = body["data_hora"]  # ISO format

    now = datetime.now(timezone.utc).isoformat()
    with get_write_db() as conn:
        cur = conn.execute(
            "INSERT INTO jogos (bolao_id, fase_id, time_casa, time_fora, data_hora, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (bolao_id, fase_id, time_casa, time_fora, data_hora, now),
        )
        jogo_id = cur.lastrowid
    increment_data_revision()
    return JSONResponse({"ok": True, "jogo_id": jogo_id})


# ──────────────────────────────────────────────────────────────────────────────
# RESULTADOS
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/resultado/lancar")
async def lancar_resultado(
    request: Request,
    user: dict = Depends(require_admin),
):
    body = await request.json()
    jogo_id = int(body["jogo_id"])
    gols_casa = int(body["gols_casa"])
    gols_fora = int(body["gols_fora"])
    classificado = body.get("classificado")
    foi_prorrogacao = int(body.get("foi_prorrogacao", 0))
    foi_penaltis = int(body.get("foi_penaltis", 0))

    now = datetime.now(timezone.utc).isoformat()

    with get_db() as conn:
        jogo = conn.execute(
            "SELECT * FROM jogos WHERE id = ?", (jogo_id,)
        ).fetchone()
    if not jogo:
        raise HTTPException(404, "Jogo não encontrado")

    with get_write_db() as conn:
        conn.execute(
            """INSERT INTO resultados
               (jogo_id, gols_casa, gols_fora, classificado, foi_prorrogacao, foi_penaltis, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(jogo_id) DO UPDATE SET
                   gols_casa=excluded.gols_casa,
                   gols_fora=excluded.gols_fora,
                   classificado=excluded.classificado,
                   foi_prorrogacao=excluded.foi_prorrogacao,
                   foi_penaltis=excluded.foi_penaltis,
                   updated_at=excluded.updated_at""",
            (jogo_id, gols_casa, gols_fora, classificado, foi_prorrogacao, foi_penaltis, now, now),
        )
        conn.execute(
            "UPDATE jogos SET status = 'finalizado' WHERE id = ?", (jogo_id,)
        )

    # Recalcula pontuação automaticamente
    processar_pontuacao_jogo(jogo_id)

    # Notifica participantes
    try:
        with get_db() as conn:
            users_ativos = conn.execute(
                """SELECT DISTINCT u.email, u.nome
                   FROM cotas c JOIN users u ON c.user_id = u.id
                   WHERE c.bolao_id = ? AND c.pago = 1""",
                (jogo["bolao_id"],),
            ).fetchall()
        for u in users_ativos:
            await enviar_resultado_lancado(
                u["email"],
                u["nome"],
                f"{jogo['time_casa']} x {jogo['time_fora']}",
                f"{gols_casa} x {gols_fora}",
            )
    except Exception:
        pass

    return JSONResponse({"ok": True})


@router.post("/resultado/{jogo_id}/reprocessar")
async def reprocessar(
    jogo_id: int,
    user: dict = Depends(require_admin),
):
    processar_pontuacao_jogo(jogo_id)
    return JSONResponse({"ok": True, "mensagem": "Pontuação reprocessada"})


# ──────────────────────────────────────────────────────────────────────────────
# RANKING E PREMIAÇÃO
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/bolao/{bolao_id}/ranking-admin", response_class=HTMLResponse)
async def ranking_admin_page(
    request: Request,
    bolao_id: int,
    user: dict = Depends(require_admin),
):
    ranking = calcular_ranking(bolao_id)
    premiacao = calcular_premiacao(bolao_id)
    with get_db() as conn:
        bolao = conn.execute("SELECT * FROM boloes WHERE id = ?", (bolao_id,)).fetchone()
    return templates.TemplateResponse(
        "admin/ranking.html",
        {
            "request": request,
            "user": user,
            "bolao": dict(bolao),
            "ranking": ranking,
            "premiacao": premiacao,
        },
    )
