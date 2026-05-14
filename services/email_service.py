"""
Serviço de e-mail via SMTP parametrizável.
Configuração via variáveis de ambiente.
"""

import os
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

logger = logging.getLogger(__name__)

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "bolao@example.com")


async def send_email(to: str, subject: str, html_body: str):
    """Envia e-mail via SMTP configurado."""
    if not SMTP_HOST:
        logger.warning("SMTP não configurado — e-mail não enviado.")
        return False

    try:
        import aiosmtplib

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=SMTP_HOST,
            port=SMTP_PORT,
            username=SMTP_USER,
            password=SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info(f"E-mail enviado para {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Falha ao enviar e-mail para {to}: {e}")
        return False


def _base_template(conteudo: str, titulo: str) -> str:
    return f"""
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; background: #0a0e1a; color: #e0e0e0; margin: 0; padding: 0; }}
  .container {{ max-width: 600px; margin: 30px auto; background: #141929; border-radius: 12px; overflow: hidden; }}
  .header {{ background: linear-gradient(135deg, #00c853, #00695c); padding: 30px 24px; text-align: center; }}
  .header h1 {{ color: #fff; margin: 0; font-size: 24px; }}
  .body {{ padding: 28px 24px; }}
  .body p {{ line-height: 1.7; color: #ccc; }}
  .btn {{ display: inline-block; padding: 12px 28px; background: #00c853; color: #fff;
          text-decoration: none; border-radius: 6px; font-weight: bold; margin: 16px 0; }}
  .footer {{ padding: 16px 24px; font-size: 12px; color: #666; border-top: 1px solid #1e2d45; }}
</style>
</head>
<body>
<div class="container">
  <div class="header"><h1>⚽ Bolão da Copa 2026</h1></div>
  <div class="body">
    <h2 style="color:#00c853">{titulo}</h2>
    {conteudo}
  </div>
  <div class="footer">Bolão da Copa 2026 · Este é um e-mail automático.</div>
</div>
</body>
</html>"""


async def enviar_boas_vindas(email: str, nome: str, bolao_nome: str):
    html = _base_template(
        f"""<p>Olá, <strong>{nome}</strong>! 🎉</p>
        <p>Sua conta foi criada com sucesso e você está participando do bolão <strong>{bolao_nome}</strong>.</p>
        <p>Acesse o sistema para enviar seus palpites antes do prazo de cada fase.</p>
        <p>Boa sorte!</p>""",
        "Bem-vindo ao Bolão!",
    )
    await send_email(email, f"Bem-vindo ao Bolão — {bolao_nome}", html)


async def enviar_confirmacao_pagamento(email: str, nome: str, numero_cota: int):
    html = _base_template(
        f"""<p>Olá, <strong>{nome}</strong>!</p>
        <p>O pagamento da sua <strong>Cota #{numero_cota}</strong> foi confirmado.</p>
        <p>Sua cota está ativa e concorre ao prêmio. Não esqueça de enviar seus palpites!</p>""",
        f"Cota #{numero_cota} confirmada ✅",
    )
    await send_email(email, f"Pagamento da Cota #{numero_cota} confirmado", html)


async def enviar_abertura_fase(email: str, nome: str, fase_nome: str, deadline: str):
    html = _base_template(
        f"""<p>Olá, <strong>{nome}</strong>!</p>
        <p>A fase <strong>{fase_nome}</strong> está aberta para palpites!</p>
        <p>Envie seus palpites até <strong>{deadline}</strong> (4h antes do primeiro jogo do dia).</p>""",
        f"Nova fase disponível: {fase_nome}",
    )
    await send_email(email, f"Fase {fase_nome} aberta para palpites", html)


async def enviar_lembrete_prazo(email: str, nome: str, jogos_pendentes: int):
    html = _base_template(
        f"""<p>Olá, <strong>{nome}</strong>!</p>
        <p>⏰ O prazo para palpites de hoje fecha em <strong>4 horas</strong>!</p>
        <p>Você ainda tem <strong>{jogos_pendentes} jogo(s)</strong> sem palpite hoje.</p>
        <p>Acesse agora e não perca os pontos!</p>""",
        "Lembrete: prazo de palpites hoje!",
    )
    await send_email(email, "Últimas horas para palpitar hoje!", html)


async def enviar_resultado_lancado(
    email: str, nome: str, jogo: str, placar: str
):
    html = _base_template(
        f"""<p>Olá, <strong>{nome}</strong>!</p>
        <p>O resultado oficial de <strong>{jogo}</strong> foi lançado.</p>
        <p>Placar: <strong>{placar}</strong></p>
        <p>Sua pontuação foi atualizada. Confira o ranking!</p>""",
        "Resultado oficial lançado",
    )
    await send_email(email, f"Resultado: {jogo} — {placar}", html)
