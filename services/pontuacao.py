"""
Serviço de pontuação — implementa todas as regras de negócio do bolão.

Regras:
- Grupos: placar exato = 5pts, resultado certo = 3pts, erro = 0pts
- Mata-mata: placar exato = 6pts base, classificado = 4pts base, vencedor = 2pts base
- Multiplicadores: oitavas x1.5, quartas x2, semi x3, final x4
- Palpite do campeão: 10 pontos extras
"""

import logging
from datetime import datetime, timezone
from database import get_db, get_write_db, increment_data_revision

logger = logging.getLogger(__name__)

# Multiplicadores por fase (slug → multiplicador)
MULTIPLICADORES = {
    "grupos": 1.0,
    "fase32": 1.5,   # Fase de 32 da Copa 2026
    "oitavas": 1.5,
    "quartas": 2.0,
    "semifinal": 3.0,
    "final": 4.0,
}

# Pontos base por categoria
PONTOS_GRUPOS = {"placar_exato": 5, "resultado": 3, "erro": 0}
PONTOS_MATA_MATA = {"placar_exato": 6, "classificado": 4, "vencedor": 2, "erro": 0}


def calcular_pontos_jogo(
    palpite_casa: int,
    palpite_fora: int,
    palpite_classificado: str | None,
    resultado_casa: int,
    resultado_fora: int,
    resultado_classificado: str | None,
    multiplicador: float,
    is_mata_mata: bool,
) -> dict:
    """
    Calcula os pontos de um palpite para um jogo.
    Retorna dict com detalhamento e total.
    """
    pontos_placar = 0.0
    pontos_classificado = 0.0
    pontos_resultado = 0.0
    tipo_acerto = "erro"

    placar_exato = (palpite_casa == resultado_casa and palpite_fora == resultado_fora)

    if not is_mata_mata:
        # --- Fase de grupos ---
        if placar_exato:
            pontos_placar = PONTOS_GRUPOS["placar_exato"]
            tipo_acerto = "placar_exato"
        else:
            # Verifica resultado (vitória casa, empate, vitória fora)
            res_palpite = _resultado_jogo(palpite_casa, palpite_fora)
            res_real = _resultado_jogo(resultado_casa, resultado_fora)
            if res_palpite == res_real:
                pontos_resultado = PONTOS_GRUPOS["resultado"]
                tipo_acerto = "resultado"
    else:
        # --- Mata-mata ---
        if placar_exato:
            pontos_placar = PONTOS_MATA_MATA["placar_exato"] * multiplicador
            tipo_acerto = "placar_exato"
        elif palpite_classificado and resultado_classificado:
            if palpite_classificado.upper() == resultado_classificado.upper():
                pontos_classificado = PONTOS_MATA_MATA["classificado"] * multiplicador
                tipo_acerto = "classificado"
            else:
                # Verifica se acertou vencedor no tempo normal (sem prorrogação)
                res_palpite = _resultado_jogo(palpite_casa, palpite_fora)
                res_real = _resultado_jogo(resultado_casa, resultado_fora)
                if res_palpite == res_real and res_palpite != "empate":
                    pontos_resultado = PONTOS_MATA_MATA["vencedor"] * multiplicador
                    tipo_acerto = "vencedor"
        else:
            # Sem campo classificado preenchido — apenas vencedor no regulamento
            res_palpite = _resultado_jogo(palpite_casa, palpite_fora)
            res_real = _resultado_jogo(resultado_casa, resultado_fora)
            if res_palpite == res_real and res_palpite != "empate":
                pontos_resultado = PONTOS_MATA_MATA["vencedor"] * multiplicador
                tipo_acerto = "vencedor"

    total = pontos_placar + pontos_classificado + pontos_resultado

    return {
        "pontos_placar": pontos_placar,
        "pontos_classificado": pontos_classificado,
        "pontos_resultado": pontos_resultado,
        "pontos_total": total,
        "tipo_acerto": tipo_acerto,
    }


def _resultado_jogo(casa: int, fora: int) -> str:
    if casa > fora:
        return "casa"
    elif fora > casa:
        return "fora"
    return "empate"


def processar_pontuacao_jogo(jogo_id: int):
    """
    Recalcula a pontuação de todas as cotas para um jogo após resultado lançado.
    """
    with get_db() as conn:
        # Busca resultado oficial
        resultado = conn.execute(
            "SELECT * FROM resultados WHERE jogo_id = ?", (jogo_id,)
        ).fetchone()
        if not resultado:
            logger.warning(f"Sem resultado para jogo {jogo_id}")
            return

        # Busca info do jogo (fase e multiplicador)
        jogo = conn.execute(
            """SELECT j.*, f.slug AS fase_slug, f.multiplicador
               FROM jogos j
               JOIN fases f ON j.fase_id = f.id
               WHERE j.id = ?""",
            (jogo_id,),
        ).fetchone()
        if not jogo:
            return

        is_mata_mata = jogo["fase_slug"] not in ("grupos",)
        multiplicador = jogo["multiplicador"]

        # Busca todos os palpites para este jogo
        palpites = conn.execute(
            "SELECT * FROM palpites WHERE jogo_id = ?", (jogo_id,)
        ).fetchall()

    with get_write_db() as conn:
        now = datetime.now(timezone.utc).isoformat()
        for p in palpites:
            pontos = calcular_pontos_jogo(
                palpite_casa=p["gols_casa"],
                palpite_fora=p["gols_fora"],
                palpite_classificado=p["classificado"],
                resultado_casa=resultado["gols_casa"],
                resultado_fora=resultado["gols_fora"],
                resultado_classificado=resultado["classificado"],
                multiplicador=multiplicador,
                is_mata_mata=is_mata_mata,
            )
            conn.execute(
                """INSERT INTO pontuacoes
                       (cota_id, jogo_id, pontos_placar, pontos_classificado,
                        pontos_resultado, pontos_total, tipo_acerto, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cota_id, jogo_id) DO UPDATE SET
                       pontos_placar=excluded.pontos_placar,
                       pontos_classificado=excluded.pontos_classificado,
                       pontos_resultado=excluded.pontos_resultado,
                       pontos_total=excluded.pontos_total,
                       tipo_acerto=excluded.tipo_acerto,
                       updated_at=excluded.updated_at""",
                (
                    p["cota_id"], jogo_id,
                    pontos["pontos_placar"], pontos["pontos_classificado"],
                    pontos["pontos_resultado"], pontos["pontos_total"],
                    pontos["tipo_acerto"], now,
                ),
            )

    increment_data_revision()
    logger.info(f"Pontuação recalculada para jogo {jogo_id} — {len(palpites)} cotas.")


def calcular_ranking(bolao_id: int) -> list:
    """
    Calcula e retorna o ranking completo do bolão, ordenado por pontuação total.
    Aplica critérios de desempate conforme regras.
    """
    with get_db() as conn:
        cotas = conn.execute(
            """SELECT c.id AS cota_id, c.numero, u.nome AS participante,
                      COALESCE(SUM(p.pontos_total), 0) AS total,
                      COALESCE(SUM(CASE WHEN p.tipo_acerto = 'placar_exato' THEN 1 ELSE 0 END), 0) AS placares_exatos,
                      COALESCE(SUM(CASE WHEN p.tipo_acerto = 'classificado' THEN 1 ELSE 0 END), 0) AS classificados,
                      COALESCE(SUM(CASE WHEN p.tipo_acerto = 'resultado' THEN 1 ELSE 0 END), 0) AS resultados,
                      pc.time_campeao
               FROM cotas c
               JOIN users u ON c.user_id = u.id
               LEFT JOIN pontuacoes p ON p.cota_id = c.id
               LEFT JOIN palpites_campeao pc ON pc.cota_id = c.id
               WHERE c.bolao_id = ? AND c.pago = 1
               GROUP BY c.id
               ORDER BY total DESC,
                        placares_exatos DESC,
                        classificados DESC,
                        resultados DESC""",
            (bolao_id,),
        ).fetchall()

        # Busca o campeão oficial se existir
        resultado_campeao = conn.execute(
            """SELECT r.classificado
               FROM jogos j
               JOIN fases f ON j.fase_id = f.id
               JOIN resultados r ON r.jogo_id = j.id
               WHERE j.bolao_id = ? AND f.slug = 'final'
               LIMIT 1""",
            (bolao_id,),
        ).fetchone()
        campeao_real = resultado_campeao["classificado"] if resultado_campeao else None

    ranking = []
    posicao = 1
    for row in cotas:
        # Bônus do campeão
        bonus_campeao = 0.0
        if campeao_real and row["time_campeao"]:
            if row["time_campeao"].upper() == campeao_real.upper():
                bonus_campeao = 10.0  # configurável futuramente

        ranking.append({
            "posicao": posicao,
            "cota_id": row["cota_id"],
            "numero_cota": row["numero"],
            "participante": row["participante"],
            "total": round(row["total"] + bonus_campeao, 2),
            "placares_exatos": row["placares_exatos"],
            "classificados": row["classificados"],
            "resultados": row["resultados"],
            "bonus_campeao": bonus_campeao,
            "time_campeao": row["time_campeao"],
        })
        posicao += 1

    return ranking


def calcular_premiacao(bolao_id: int) -> list:
    """
    Calcula a distribuição de prêmios para as 5 primeiras cotas.
    """
    with get_db() as conn:
        bolao = conn.execute(
            "SELECT * FROM boloes WHERE id = ?", (bolao_id,)
        ).fetchone()
        if not bolao:
            return []

        total_cotas = conn.execute(
            "SELECT COUNT(*) AS cnt FROM cotas WHERE bolao_id = ? AND pago = 1",
            (bolao_id,),
        ).fetchone()["cnt"]

    total_premio = total_cotas * bolao["valor_cota"]
    ranking = calcular_ranking(bolao_id)[:5]

    percentuais = [
        bolao["divisao_1"],
        bolao["divisao_2"],
        bolao["divisao_3"],
        bolao["divisao_4"],
        bolao["divisao_5"],
    ]

    premiacao = []
    for i, cota in enumerate(ranking):
        pct = percentuais[i] if i < len(percentuais) else 0
        valor = round(total_premio * pct / 100, 2)
        premiacao.append({**cota, "percentual": pct, "valor_premio": valor})

    return premiacao
