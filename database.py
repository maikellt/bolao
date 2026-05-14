"""
Gerenciamento de banco de dados — Turso como fonte de verdade,
SQLite local como camada de aceleração de leitura.
"""

import sqlite3
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Versão esperada do schema
SCHEMA_VERSION = 1

# Caminho da base local
LOCAL_DB_PATH = os.getenv("LOCAL_DB_PATH", "/tmp/bolao_local.db")

# URL e token do Turso
TURSO_URL = os.getenv("TURSO_DATABASE_URL", "")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "")


def get_local_connection() -> sqlite3.Connection:
    """Retorna conexão com a base SQLite local."""
    conn = sqlite3.connect(LOCAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_turso_connection():
    """Retorna conexão com o Turso remoto."""
    try:
        import libsql_experimental as libsql
        conn = libsql.connect(database=TURSO_URL, auth_token=TURSO_TOKEN)
        return conn
    except Exception as e:
        logger.error(f"Falha ao conectar ao Turso: {e}")
        raise


def get_turso_sync_connection():
    """Retorna conexão sincronizada Turso → local (embedded replica)."""
    try:
        import libsql_experimental as libsql
        conn = libsql.connect(
            database=LOCAL_DB_PATH,
            sync_url=TURSO_URL,
            auth_token=TURSO_TOKEN,
        )
        conn.sync()
        return conn
    except Exception as e:
        logger.warning(f"Falha na conexão sincronizada — usando local puro: {e}")
        return get_local_connection()


@contextmanager
def get_db():
    """Context manager para conexão de leitura (local)."""
    conn = get_local_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_write_db():
    """Context manager para escrita — prioriza Turso remoto."""
    if TURSO_URL and TURSO_TOKEN:
        try:
            conn = get_turso_connection()
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
            # Sincroniza local após escrita remota
            _sync_local_after_write()
            return
        except Exception as e:
            logger.warning(f"Escrita remota falhou, usando local: {e}")

    conn = get_local_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sync_local_after_write():
    """Sincroniza a réplica local após uma escrita remota."""
    try:
        if TURSO_URL and TURSO_TOKEN:
            conn = get_turso_sync_connection()
            conn.sync()
            conn.close()
    except Exception as e:
        logger.warning(f"Sincronização pós-escrita falhou: {e}")


def get_local_schema_version() -> int:
    """Retorna a versão atual do schema local."""
    try:
        conn = get_local_connection()
        cur = conn.execute("PRAGMA user_version")
        version = cur.fetchone()[0]
        conn.close()
        return version
    except Exception:
        return 0


def get_local_data_revision() -> str:
    """Retorna a revisão lógica dos dados locais."""
    try:
        conn = get_local_connection()
        cur = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'data_revision'"
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else "0"
    except Exception:
        return "0"


def get_remote_data_revision() -> str:
    """Consulta a revisão remota no Turso."""
    if not TURSO_URL:
        return "0"
    try:
        conn = get_turso_connection()
        cur = conn.execute(
            "SELECT value FROM app_meta WHERE key = 'data_revision'"
        )
        row = cur.fetchone()
        conn.close()
        return row[0] if row else "0"
    except Exception:
        return "0"


def increment_data_revision():
    """Incrementa a revisão dos dados após escritas críticas."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        with get_write_db() as conn:
            cur = conn.execute(
                "SELECT value FROM app_meta WHERE key = 'data_revision'"
            )
            row = cur.fetchone()
            current = int(row[0]) if row else 0
            new_rev = str(current + 1)
            conn.execute(
                """INSERT INTO app_meta (key, value, updated_at)
                   VALUES ('data_revision', ?, ?)
                   ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at""",
                (new_rev, now),
            )
    except Exception as e:
        logger.error(f"Erro ao incrementar revisão: {e}")


DDL_SCHEMA = """
-- Controle da aplicação
CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Usuários
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    senha_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Bolões
CREATE TABLE IF NOT EXISTS boloes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    descricao TEXT,
    status TEXT NOT NULL DEFAULT 'ativo',
    valor_cota REAL NOT NULL DEFAULT 20.0,
    divisao_1 REAL NOT NULL DEFAULT 40.0,
    divisao_2 REAL NOT NULL DEFAULT 25.0,
    divisao_3 REAL NOT NULL DEFAULT 15.0,
    divisao_4 REAL NOT NULL DEFAULT 10.0,
    divisao_5 REAL NOT NULL DEFAULT 10.0,
    pontos_campeao REAL NOT NULL DEFAULT 10.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Convites
CREATE TABLE IF NOT EXISTS convites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bolao_id INTEGER NOT NULL REFERENCES boloes(id),
    token TEXT UNIQUE NOT NULL,
    email_destino TEXT,
    usado INTEGER NOT NULL DEFAULT 0,
    expira_em TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Cotas
CREATE TABLE IF NOT EXISTS cotas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bolao_id INTEGER NOT NULL REFERENCES boloes(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    numero INTEGER NOT NULL,
    pago INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(bolao_id, user_id, numero)
);

-- Fases
CREATE TABLE IF NOT EXISTS fases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bolao_id INTEGER NOT NULL REFERENCES boloes(id),
    nome TEXT NOT NULL,
    slug TEXT NOT NULL,
    ordem INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'nao_iniciada',
    multiplicador REAL NOT NULL DEFAULT 1.0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(bolao_id, slug)
);

-- Jogos
CREATE TABLE IF NOT EXISTS jogos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bolao_id INTEGER NOT NULL REFERENCES boloes(id),
    fase_id INTEGER NOT NULL REFERENCES fases(id),
    time_casa TEXT NOT NULL,
    time_fora TEXT NOT NULL,
    data_hora TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'agendado',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Resultados oficiais
CREATE TABLE IF NOT EXISTS resultados (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    jogo_id INTEGER UNIQUE NOT NULL REFERENCES jogos(id),
    gols_casa INTEGER NOT NULL,
    gols_fora INTEGER NOT NULL,
    classificado TEXT,
    foi_prorrogacao INTEGER NOT NULL DEFAULT 0,
    foi_penaltis INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Palpites
CREATE TABLE IF NOT EXISTS palpites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cota_id INTEGER NOT NULL REFERENCES cotas(id),
    jogo_id INTEGER NOT NULL REFERENCES jogos(id),
    gols_casa INTEGER NOT NULL,
    gols_fora INTEGER NOT NULL,
    classificado TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(cota_id, jogo_id)
);

-- Palpites do campeão
CREATE TABLE IF NOT EXISTS palpites_campeao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cota_id INTEGER UNIQUE NOT NULL REFERENCES cotas(id),
    time_campeao TEXT NOT NULL,
    bloqueado INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Pontuações calculadas
CREATE TABLE IF NOT EXISTS pontuacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cota_id INTEGER NOT NULL REFERENCES cotas(id),
    jogo_id INTEGER NOT NULL REFERENCES jogos(id),
    pontos_placar REAL NOT NULL DEFAULT 0,
    pontos_classificado REAL NOT NULL DEFAULT 0,
    pontos_resultado REAL NOT NULL DEFAULT 0,
    pontos_total REAL NOT NULL DEFAULT 0,
    tipo_acerto TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(cota_id, jogo_id)
);

-- Índices
CREATE INDEX IF NOT EXISTS idx_cotas_bolao ON cotas(bolao_id);
CREATE INDEX IF NOT EXISTS idx_cotas_user ON cotas(user_id);
CREATE INDEX IF NOT EXISTS idx_jogos_fase ON jogos(fase_id);
CREATE INDEX IF NOT EXISTS idx_palpites_cota ON palpites(cota_id);
CREATE INDEX IF NOT EXISTS idx_palpites_jogo ON palpites(jogo_id);
CREATE INDEX IF NOT EXISTS idx_pontuacoes_cota ON pontuacoes(cota_id);
"""


def _apply_migrations(conn):
    """Aplica migrações de schema se necessário."""
    cur = conn.execute("PRAGMA user_version")
    current = cur.fetchone()[0]
    if current < SCHEMA_VERSION:
        logger.info(f"Aplicando schema (versão {current} → {SCHEMA_VERSION})")
        conn.executescript(DDL_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()

        # Seed de dados iniciais
        _seed_initial_data(conn)
        logger.info("Schema aplicado com sucesso.")


def _seed_initial_data(conn):
    """Insere dados iniciais de configuração."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO app_meta (key, value, updated_at)
           VALUES ('schema_version', ?, ?),
                  ('data_revision', '0', ?),
                  ('last_sync_at', ?, ?)""",
        (str(SCHEMA_VERSION), now, now, now, now),
    )


def initialize_database():
    """
    Inicializa o banco de dados local.
    Tenta sincronizar com Turso se disponível, caso contrário cria local.
    """
    logger.info("Inicializando banco de dados...")

    local_version = get_local_schema_version()

    if TURSO_URL and TURSO_TOKEN:
        try:
            logger.info("Tentando réplica sincronizada com Turso...")
            conn = get_turso_sync_connection()
            _apply_migrations(conn)
            if hasattr(conn, 'sync'):
                conn.sync()
            conn.close()
            logger.info("Banco inicializado via Turso sync.")
            return
        except Exception as e:
            logger.warning(f"Sync Turso falhou, usando SQLite local: {e}")

    # Fallback para SQLite local puro
    conn = get_local_connection()
    _apply_migrations(conn)
    conn.close()
    logger.info("Banco inicializado localmente.")
