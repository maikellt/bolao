"""
Bolão da Copa 2026 — Aplicação principal.
"""

import os
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

load_dotenv()

# Configura logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização da aplicação — banco de dados e scheduler."""
    from database import initialize_database
    initialize_database()
    logger.info("Banco de dados inicializado.")

    # Cria conta admin padrão se não existir
    _create_default_admin()

    # Inicia scheduler de tarefas periódicas
    _start_scheduler()

    yield

    logger.info("Aplicação encerrada.")


app = FastAPI(
    title="Bolão da Copa 2026",
    version="1.0.0",
    lifespan=lifespan,
)

# Arquivos estáticos
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")

# Registra rotas
from routes.auth import router as auth_router
from routes.admin import router as admin_router
from routes.participante import router as participante_router
from routes.palpites import router as palpites_router

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(participante_router)
app.include_router(palpites_router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    from auth import get_current_user_from_request
    user = get_current_user_from_request(request)
    if user:
        if user.get("is_admin"):
            return RedirectResponse("/admin")
        return RedirectResponse("/dashboard")
    return RedirectResponse("/login")


@app.exception_handler(404)
async def not_found(request: Request, exc):
    return templates.TemplateResponse(
        "erro.html",
        {"request": request, "mensagem": "Página não encontrada."},
        status_code=404,
    )


@app.exception_handler(403)
async def forbidden(request: Request, exc):
    return templates.TemplateResponse(
        "erro.html",
        {"request": request, "mensagem": "Acesso não autorizado."},
        status_code=403,
    )


def _create_default_admin():
    """Cria o usuário admin padrão se não existir."""
    from database import get_db, get_write_db
    from auth import hash_password

    admin_email = os.getenv("ADMIN_EMAIL", "admin@bolao.local")
    admin_senha = os.getenv("ADMIN_PASSWORD", "admin123")
    admin_nome = os.getenv("ADMIN_NAME", "Organizador")

    with get_db() as conn:
        existe = conn.execute(
            "SELECT id FROM users WHERE email = ?", (admin_email,)
        ).fetchone()

    if not existe:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with get_write_db() as conn:
            conn.execute(
                "INSERT INTO users (nome, email, senha_hash, is_admin, created_at) VALUES (?, ?, ?, 1, ?)",
                (admin_nome, admin_email, hash_password(admin_senha), now),
            )
        logger.info(f"Admin criado: {admin_email}")


def _start_scheduler():
    """Inicia tarefas agendadas — lembretes de e-mail."""
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        scheduler = AsyncIOScheduler()

        # Verifica lembretes uma vez por hora
        scheduler.add_job(
            _verificar_lembretes_diarios,
            CronTrigger(minute=0),  # No início de cada hora
            id="lembretes_diarios",
        )
        scheduler.start()
        logger.info("Scheduler de lembretes iniciado.")
    except Exception as e:
        logger.warning(f"Scheduler não iniciado: {e}")


async def _verificar_lembretes_diarios():
    """
    Verifica se há jogos em ~4h e envia lembretes para cotas com palpites pendentes.
    """
    from datetime import datetime, timedelta, timezone
    from database import get_db
    from services.email_service import enviar_lembrete_prazo

    now = datetime.now(timezone.utc)
    janela_inicio = now + timedelta(hours=3, minutes=55)
    janela_fim = now + timedelta(hours=4, minutes=5)

    try:
        with get_db() as conn:
            # Busca bolões com jogos na janela de bloqueio
            jogos_prestes = conn.execute(
                """SELECT DISTINCT j.bolao_id, substr(j.data_hora, 1, 10) AS dia
                   FROM jogos j
                   WHERE j.data_hora BETWEEN ? AND ?""",
                (janela_inicio.isoformat(), janela_fim.isoformat()),
            ).fetchall()

            for jp in jogos_prestes:
                bolao_id = jp["bolao_id"]
                dia = jp["dia"]

                # Jogos do dia
                jogos_dia = conn.execute(
                    """SELECT id FROM jogos
                       WHERE bolao_id = ? AND substr(data_hora, 1, 10) = ?""",
                    (bolao_id, dia),
                ).fetchall()
                jogo_ids = [j["id"] for j in jogos_dia]
                if not jogo_ids:
                    continue

                ph = ",".join(["?" for _ in jogo_ids])

                # Cotas com palpites pendentes
                cotas_pendentes = conn.execute(
                    f"""SELECT DISTINCT c.id AS cota_id, u.email, u.nome,
                               COUNT(j.id) - COUNT(p.id) AS pendentes
                        FROM cotas c
                        JOIN users u ON c.user_id = u.id
                        CROSS JOIN (SELECT id FROM jogos WHERE id IN ({ph})) j
                        LEFT JOIN palpites p ON p.cota_id = c.id AND p.jogo_id = j.id
                        WHERE c.bolao_id = ? AND c.pago = 1
                        GROUP BY c.id
                        HAVING pendentes > 0""",
                    jogo_ids + [bolao_id],
                ).fetchall()

                for cota in cotas_pendentes:
                    try:
                        await enviar_lembrete_prazo(
                            cota["email"], cota["nome"], cota["pendentes"]
                        )
                    except Exception as e:
                        logger.warning(f"Lembrete não enviado: {e}")

    except Exception as e:
        logger.error(f"Erro no scheduler de lembretes: {e}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)
