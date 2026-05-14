"""
Rotas de autenticação — cadastro via convite, login, logout.
"""

import secrets
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from auth import hash_password, verify_password, create_access_token, require_auth
from database import get_db, get_write_db, increment_data_revision
from services.email_service import enviar_boas_vindas

router = APIRouter()
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(
    request: Request,
    email: str = Form(...),
    senha: str = Form(...),
):
    with get_db() as conn:
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)
        ).fetchone()

    if not user or not verify_password(senha, user["senha_hash"]):
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "erro": "E-mail ou senha incorretos"},
            status_code=400,
        )

    token = create_access_token({
        "sub": str(user["id"]),
        "email": user["email"],
        "nome": user["nome"],
        "is_admin": bool(user["is_admin"]),
    })

    resp = RedirectResponse(
        url="/admin" if user["is_admin"] else "/dashboard",
        status_code=302,
    )
    resp.set_cookie("access_token", token, httponly=True, max_age=60 * 60 * 24 * 7)
    return resp


@router.get("/logout")
async def logout():
    resp = RedirectResponse(url="/login", status_code=302)
    resp.delete_cookie("access_token")
    return resp


@router.get("/convite/{token}", response_class=HTMLResponse)
async def convite_page(request: Request, token: str):
    with get_db() as conn:
        convite = conn.execute(
            """SELECT c.*, b.nome AS bolao_nome
               FROM convites c JOIN boloes b ON c.bolao_id = b.id
               WHERE c.token = ? AND c.usado = 0""",
            (token,),
        ).fetchone()

    if not convite:
        return templates.TemplateResponse(
            "erro.html",
            {"request": request, "mensagem": "Convite inválido ou já utilizado."},
        )

    expira = datetime.fromisoformat(convite["expira_em"].replace("Z", "+00:00"))
    if expira < datetime.now(timezone.utc):
        return templates.TemplateResponse(
            "erro.html",
            {"request": request, "mensagem": "Convite expirado."},
        )

    return templates.TemplateResponse(
        "register.html",
        {"request": request, "convite": dict(convite), "token": token},
    )


@router.post("/convite/{token}/cadastrar")
async def cadastrar(
    request: Request,
    token: str,
    nome: str = Form(...),
    email: str = Form(...),
    senha: str = Form(...),
):
    with get_db() as conn:
        convite = conn.execute(
            "SELECT * FROM convites WHERE token = ? AND usado = 0",
            (token,),
        ).fetchone()

    if not convite:
        raise HTTPException(400, "Convite inválido")

    email = email.lower().strip()
    with get_db() as conn:
        existe = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email,)
        ).fetchone()
    if existe:
        return templates.TemplateResponse(
            "register.html",
            {
                "request": request,
                "token": token,
                "convite": dict(convite),
                "erro": "E-mail já cadastrado",
            },
            status_code=400,
        )

    now = datetime.now(timezone.utc).isoformat()
    with get_write_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (nome, email, senha_hash, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
            (nome.strip(), email, hash_password(senha), now),
        )
        user_id = cur.lastrowid
        conn.execute(
            "UPDATE convites SET usado = 1 WHERE token = ?", (token,)
        )

    increment_data_revision()

    # Busca nome do bolão para e-mail
    with get_db() as conn:
        bolao = conn.execute(
            "SELECT nome FROM boloes WHERE id = ?", (convite["bolao_id"],)
        ).fetchone()
    bolao_nome = bolao["nome"] if bolao else "Bolão"

    try:
        await enviar_boas_vindas(email, nome, bolao_nome)
    except Exception:
        pass

    token_jwt = create_access_token({
        "sub": str(user_id),
        "email": email,
        "nome": nome.strip(),
        "is_admin": False,
    })
    resp = RedirectResponse(url="/dashboard", status_code=302)
    resp.set_cookie("access_token", token_jwt, httponly=True, max_age=60 * 60 * 24 * 7)
    return resp
