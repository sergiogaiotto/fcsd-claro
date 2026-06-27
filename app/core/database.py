import json
import os
import re
from typing import Any

from sqlalchemy import create_engine, text, inspect

from app.core.config import settings
from app.core import db_engine
from app.core.db_engine import DialectConnection, column_exists, table_exists

# SQLAlchemy engine (used by the agent SQL toolkit + pandas to_sql).
# Tuning rationale (Render free/starter, single web instance):
#   - pool_size=5 / max_overflow=5 — up to 10 connections in this engine,
#     same budget as the psycopg_pool used by db_engine.connect(); both
#     pools combined leave plenty of headroom under managed-Postgres limits.
#   - pool_pre_ping=True — psycopg checks each conn before handing it out;
#     dead/stale conns (Postgres or proxy timeouts) get replaced silently
#     instead of bubbling a "server closed the connection unexpectedly".
#   - pool_recycle=1800 — recycle conns every 30 min so the server's idle
#     timeout doesn't pull the rug out from under us.
engine = create_engine(
    settings.database_url,
    echo=False,
    future=True,
    pool_size=max(1, settings.db_sqlalchemy_pool_size),
    max_overflow=max(0, settings.db_sqlalchemy_max_overflow),
    pool_pre_ping=True,
    pool_use_lifo=True,
    pool_recycle=max(60, settings.db_sqlalchemy_pool_recycle_seconds),
    connect_args={
        "connect_timeout": max(1, settings.db_connect_timeout_seconds),
        "prepare_threshold": 3,
    },
)


def _is_safe_identifier(name: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name or ""))


def _validate_select_only_sql(sql: str) -> str | None:
    statement = (sql or "").strip()
    if not statement:
        return "Consulta vazia."
    if ";" in statement.rstrip(";"):
        return "Múltiplas instruções SQL não são permitidas."

    upper = statement.upper()
    if not (upper.startswith("SELECT") or upper.startswith("WITH")):
        return "Apenas instruções SELECT/WITH são permitidas."

    forbidden = {
        "DROP", "DELETE", "UPDATE", "INSERT", "ALTER",
        "CREATE", "REPLACE", "TRUNCATE", "ATTACH", "DETACH",
        # Funções perigosas (leitura de arquivo/rede/IO e DoS) — nunca aparecem em
        # analytics legítimo; defense-in-depth p/ TODO caminho de leitura.
        "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "PG_STAT_FILE",
        "LO_IMPORT", "LO_EXPORT", "DBLINK", "PG_SLEEP",
    }
    tokens = re.findall(r"[A-Z_]+", upper)
    for token in tokens:
        if token in forbidden:
            return f"Comando '{token}' não é permitido em consultas de leitura."
    return None


def get_sync_connection() -> DialectConnection:
    """Open a connection to the configured PostgreSQL database.

    Returns a ``DialectConnection`` that exposes the subset of the sqlite3
    DB-API used across the codebase (execute / cursor / commit / rollback /
    close, plus context-manager). The wrapper translates ``?``-style
    placeholders to ``%s`` and gives mapping-style row access via psycopg's
    ``dict_row`` factory, so historical call sites keep working unchanged.
    """
    return db_engine.connect()


def _exec_returning_id(conn: DialectConnection, sql: str, params: tuple) -> int:
    """Run an INSERT and return the new row's primary key.

    Postgres has no ``last_insert_rowid()``; this helper appends
    ``RETURNING id`` when the SQL does not already include a RETURNING
    clause and reads the value off the cursor.
    """
    if " RETURNING " not in sql.upper():
        sql = sql.rstrip(";") + " RETURNING id"
    cur = conn.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        raise RuntimeError("INSERT did not return an id")
    return row["id"] if isinstance(row, dict) else row[0]


# ---------------------------------------------------------------------------
# Internal table set (excluded from user-facing listings)
# ---------------------------------------------------------------------------
INTERNAL_TABLES = {
    "analysis_types", "api_keys", "query_history", "analysis_gallery",
    "users", "sessions", "custom_skills",
    "datamarts", "datamart_tables", "user_datamarts",
    "diamond_layers", "diamond_layer_tables", "user_diamond_layers",
    "saved_visions", "cockpit_tiles",
    "saved_questions","catalog_datasets", "catalog_columns", "catalog_relationships",
    "json_sources", "data_products", "shared_results", "reports", "exec_decks",
    "codegen_tables", "codegen_snippets", "codegen_runs",
    "codegen_techniques", "codegen_patterns", "codegen_chats",
    "playbooks", "failures", "app_settings",
}


_DDL_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS users (
        id BIGSERIAL PRIMARY KEY,
        login TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        user_type TEXT NOT NULL DEFAULT 'user' CHECK(user_type IN ('root','superuser','admin','analista','engenheiro_dados','user')),
        display_name TEXT NOT NULL DEFAULT '',
        profile_description TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id BIGSERIAL PRIMARY KEY,
        token TEXT NOT NULL UNIQUE,
        user_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS custom_skills (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL DEFAULT '',
        triggers TEXT NOT NULL DEFAULT '[]',
        trust_level INTEGER NOT NULL DEFAULT 1,
        priority INTEGER NOT NULL DEFAULT 10,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL DEFAULT '',
        owner_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_types (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        system_prompt TEXT NOT NULL DEFAULT '',
        guardrails_input TEXT NOT NULL DEFAULT '',
        guardrails_output TEXT NOT NULL DEFAULT '',
        owner_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS api_keys (
        id BIGSERIAL PRIMARY KEY,
        key_hash TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS query_history (
        id BIGSERIAL PRIMARY KEY,
        question TEXT NOT NULL,
        sql_generated TEXT,
        result_summary TEXT,
        analysis_type_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (analysis_type_id) REFERENCES analysis_types(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS analysis_gallery (
        id BIGSERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        query_data TEXT NOT NULL,
        chart_config TEXT NOT NULL DEFAULT '',
        page_html TEXT NOT NULL DEFAULT '',
        share_token TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS datamarts (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS datamart_tables (
        id BIGSERIAL PRIMARY KEY,
        datamart_id INTEGER NOT NULL,
        table_name TEXT NOT NULL,
        FOREIGN KEY (datamart_id) REFERENCES datamarts(id) ON DELETE CASCADE,
        UNIQUE(datamart_id, table_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_datamarts (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        datamart_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (datamart_id) REFERENCES datamarts(id) ON DELETE CASCADE,
        UNIQUE(user_id, datamart_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS diamond_layers (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS diamond_layer_tables (
        id BIGSERIAL PRIMARY KEY,
        layer_id INTEGER NOT NULL,
        table_name TEXT NOT NULL,
        owner_id INTEGER,
        assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (layer_id) REFERENCES diamond_layers(id) ON DELETE CASCADE,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL,
        UNIQUE(layer_id, table_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS user_diamond_layers (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        layer_id INTEGER NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (layer_id) REFERENCES diamond_layers(id) ON DELETE CASCADE,
        UNIQUE(user_id, layer_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS saved_questions (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        label TEXT NOT NULL DEFAULT '',
        sql_generated TEXT NOT NULL DEFAULT '',
        is_favorite INTEGER NOT NULL DEFAULT 0,
        param_config TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS saved_visions (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        question TEXT NOT NULL DEFAULT '',
        sql_generated TEXT NOT NULL DEFAULT '',
        label TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS reports (
        id BIGSERIAL PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published','archived')),
        question TEXT NOT NULL DEFAULT '',
        sql_generated TEXT NOT NULL DEFAULT '',
        datamart_ids TEXT NOT NULL DEFAULT '[]',
        definition TEXT NOT NULL DEFAULT '{}',
        version INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exec_decks (
        id BIGSERIAL PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        question TEXT NOT NULL DEFAULT '',
        datamart_ids TEXT NOT NULL DEFAULT '[]',
        diamond_layer_ids TEXT NOT NULL DEFAULT '[]',
        deck_spec TEXT NOT NULL DEFAULT '{}',
        n_slides INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS shared_results (
        id BIGSERIAL PRIMARY KEY,
        sender_id INTEGER NOT NULL,
        recipient_id INTEGER NOT NULL,
        question TEXT NOT NULL,
        sql_generated TEXT NOT NULL DEFAULT '',
        datamart_ids TEXT NOT NULL DEFAULT '[]',
        label TEXT NOT NULL DEFAULT '',
        message TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        read_at TIMESTAMP,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (recipient_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_datasets (
        id BIGSERIAL PRIMARY KEY,
        table_name TEXT NOT NULL UNIQUE,
        description TEXT NOT NULL DEFAULT '',
        domain TEXT NOT NULL DEFAULT 'Geral',
        owner TEXT NOT NULL DEFAULT '',
        quality_score REAL NOT NULL DEFAULT 0,
        quality_detail TEXT NOT NULL DEFAULT '{}',
        entities TEXT NOT NULL DEFAULT '[]',
        extras TEXT NOT NULL DEFAULT '{}',
        tags TEXT NOT NULL DEFAULT '[]',
        row_count INTEGER NOT NULL DEFAULT 0,
        col_count INTEGER NOT NULL DEFAULT 0,
        enriched_at TEXT NOT NULL DEFAULT '',
        scanned_at TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_columns (
        id BIGSERIAL PRIMARY KEY,
        table_name TEXT NOT NULL,
        column_name TEXT NOT NULL,
        technical_type TEXT NOT NULL DEFAULT '',
        semantic_type TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        classification TEXT NOT NULL DEFAULT '',
        profile_data TEXT NOT NULL DEFAULT '{}',
        pii_data TEXT NOT NULL DEFAULT '{}',
        tags TEXT NOT NULL DEFAULT '[]',
        enriched_at TEXT NOT NULL DEFAULT '',
        scanned_at TEXT NOT NULL DEFAULT '',
        UNIQUE(table_name, column_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS catalog_relationships (
        id BIGSERIAL PRIMARY KEY,
        source_table TEXT NOT NULL,
        source_column TEXT NOT NULL,
        target_table TEXT NOT NULL,
        target_column TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0,
        rel_type TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cockpit_tiles (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        vision_id INTEGER NOT NULL,
        chart_type TEXT NOT NULL DEFAULT 'bar',
        x_field TEXT NOT NULL DEFAULT '',
        y_field TEXT NOT NULL DEFAULT '',
        agg TEXT NOT NULL DEFAULT 'sum',
        position INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (vision_id) REFERENCES saved_visions(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS json_sources (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        url_template TEXT NOT NULL DEFAULT '',
        table_name TEXT NOT NULL DEFAULT '',
        json_path TEXT NOT NULL DEFAULT '',
        date_format TEXT NOT NULL DEFAULT 'yyyy-MM-dd',
        http_headers TEXT NOT NULL DEFAULT '{}',
        append_mode INTEGER NOT NULL DEFAULT 0,
        datamart_id INTEGER,
        description TEXT NOT NULL DEFAULT '',
        last_imported_at TEXT NOT NULL DEFAULT '',
        last_rows_imported INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (datamart_id) REFERENCES datamarts(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS data_products (
        id BIGSERIAL PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL DEFAULT '',
        version TEXT NOT NULL DEFAULT '1.0.0',
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','active','deprecated','retired')),
        domain TEXT NOT NULL DEFAULT '',
        purpose TEXT NOT NULL DEFAULT '',
        business_value TEXT NOT NULL DEFAULT '',
        consumers TEXT NOT NULL DEFAULT '[]',
        owner_team TEXT NOT NULL DEFAULT '',
        owner_email TEXT NOT NULL DEFAULT '',
        owner_role TEXT NOT NULL DEFAULT 'data product owner',
        classification TEXT NOT NULL DEFAULT 'internal' CHECK(classification IN ('public','internal','restricted')),
        compliance TEXT NOT NULL DEFAULT '[]',
        tags TEXT NOT NULL DEFAULT '{}',
        artifacts TEXT NOT NULL DEFAULT '[]',
        input_ports TEXT NOT NULL DEFAULT '[]',
        output_ports TEXT NOT NULL DEFAULT '[]',
        quality_rules TEXT NOT NULL DEFAULT '[]',
        sla_freshness TEXT NOT NULL DEFAULT '',
        sla_availability TEXT NOT NULL DEFAULT '',
        value_layer TEXT NOT NULL DEFAULT 'refined' CHECK(value_layer IN ('raw','refined','insight')),
        consumption_type TEXT NOT NULL DEFAULT 'analytical' CHECK(consumption_type IN ('analytical','operational','ml_ai')),
        nomenclature TEXT NOT NULL DEFAULT '',
        created_by TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codegen_tables (
        id BIGSERIAL PRIMARY KEY,
        table_name TEXT NOT NULL UNIQUE,
        owner_id INTEGER NOT NULL,
        datamart_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (datamart_id) REFERENCES datamarts(id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codegen_snippets (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        sql TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        UNIQUE(user_id, name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codegen_runs (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL,
        sql TEXT NOT NULL DEFAULT '',
        kind TEXT NOT NULL DEFAULT 'read',
        row_count INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codegen_techniques (
        id BIGSERIAL PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        runtime TEXT NOT NULL DEFAULT 'python',
        description TEXT NOT NULL DEFAULT '',
        frag_imports TEXT NOT NULL DEFAULT '',
        frag_setup TEXT NOT NULL DEFAULT '',
        frag_read TEXT NOT NULL DEFAULT '',
        frag_show TEXT NOT NULL DEFAULT '',
        frag_teardown TEXT NOT NULL DEFAULT '',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codegen_patterns (
        id BIGSERIAL PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        label TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        template TEXT NOT NULL DEFAULT '',
        compatible TEXT NOT NULL DEFAULT '*',
        params_schema TEXT NOT NULL DEFAULT '[]',
        is_active INTEGER NOT NULL DEFAULT 1,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS codegen_chats (
        id BIGSERIAL PRIMARY KEY,
        owner_id BIGINT NOT NULL,
        title TEXT NOT NULL DEFAULT 'Nova conversa',
        messages TEXT NOT NULL DEFAULT '[]',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS playbooks (
        id BIGSERIAL PRIMARY KEY,
        owner_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '',
        description TEXT NOT NULL DEFAULT '',
        emoji TEXT NOT NULL DEFAULT '📊',
        questions TEXT NOT NULL DEFAULT '[]',
        datamart_ids TEXT NOT NULL DEFAULT '[]',
        diamond_layer_ids TEXT NOT NULL DEFAULT '[]',
        visibility TEXT NOT NULL DEFAULT 'private' CHECK(visibility IN ('private','shared')),
        is_system INTEGER NOT NULL DEFAULT 0,
        created_by TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS failures (
        id BIGSERIAL PRIMARY KEY,
        user_id INTEGER,
        user_login TEXT NOT NULL DEFAULT '',
        user_name TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'query',
        question TEXT NOT NULL DEFAULT '',
        sql_generated TEXT NOT NULL DEFAULT '',
        error_message TEXT NOT NULL DEFAULT '',
        error_type TEXT NOT NULL DEFAULT '',
        traceback TEXT NOT NULL DEFAULT '',
        response_text TEXT NOT NULL DEFAULT '',
        snapshot_html TEXT NOT NULL DEFAULT '',
        screenshot TEXT NOT NULL DEFAULT '',
        model TEXT NOT NULL DEFAULT '',
        analysis_type_id INTEGER,
        datamart_ids TEXT NOT NULL DEFAULT '[]',
        diamond_layer_ids TEXT NOT NULL DEFAULT '[]',
        auto_corrected INTEGER NOT NULL DEFAULT 0,
        corrected_sql TEXT NOT NULL DEFAULT '',
        duration_ms INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','resolved')),
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
    )
    """,
]

# Indexes — created AFTER all CREATE TABLE statements have run, so an
# index that references a table declared later in the DDL list still
# resolves cleanly. Previously these were interleaved with the CREATE
# TABLE list, which caused ``UndefinedTable: relation "X" does not exist``
# on first boot when the index came before its target table.
_INDEX_STATEMENTS: list[str] = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_login_lower ON users (LOWER(login))",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_datamarts_name_lower ON datamarts (LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_reports_owner ON reports(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_reports_status ON reports(status)",
    "CREATE INDEX IF NOT EXISTS idx_shared_results_recipient ON shared_results(recipient_id, read_at)",
    "CREATE INDEX IF NOT EXISTS idx_shared_results_sender ON shared_results(sender_id)",
    # Hot WHERE clauses — added for performance, idempotent on re-runs
    "CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_custom_skills_active ON custom_skills(is_active) WHERE is_active = 1",
    "CREATE INDEX IF NOT EXISTS idx_custom_skills_owner ON custom_skills(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_analysis_types_owner ON analysis_types(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_user_datamarts_user ON user_datamarts(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_datamart_tables_table ON datamart_tables(table_name)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_diamond_layers_name_lower ON diamond_layers (LOWER(name))",
    "CREATE INDEX IF NOT EXISTS idx_user_diamond_layers_user ON user_diamond_layers(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_diamond_layer_tables_table ON diamond_layer_tables(table_name)",
    "CREATE INDEX IF NOT EXISTS idx_diamond_layer_tables_owner ON diamond_layer_tables(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_saved_questions_user ON saved_questions(user_id, is_favorite)",
    "CREATE INDEX IF NOT EXISTS idx_saved_visions_user ON saved_visions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_query_history_created ON query_history(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_query_history_user ON query_history(user_login, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_cockpit_tiles_user ON cockpit_tiles(user_id, position)",
    "CREATE INDEX IF NOT EXISTS idx_codegen_tables_owner ON codegen_tables(owner_id)",
    "CREATE INDEX IF NOT EXISTS idx_codegen_snippets_user ON codegen_snippets(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_codegen_runs_user ON codegen_runs(user_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_codegen_chats_owner ON codegen_chats(owner_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_playbooks_owner ON playbooks(owner_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_playbooks_visibility ON playbooks(visibility)",
    "CREATE INDEX IF NOT EXISTS idx_failures_created ON failures(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_failures_user ON failures(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_failures_status ON failures(status)",
]

# Per-table list of (column_name, column_definition) tuples added in
# subsequent versions. ``column_exists`` skips already-applied migrations.
_COLUMN_MIGRATIONS: dict[str, list[tuple[str, str]]] = {
    "analysis_gallery": [
        ("page_html", "TEXT NOT NULL DEFAULT ''"),
        ("category", "TEXT NOT NULL DEFAULT 'analysis'"),
    ],
    "saved_questions": [
        ("sql_generated", "TEXT NOT NULL DEFAULT ''"),
        ("is_favorite", "INTEGER NOT NULL DEFAULT 0"),
        ("param_config", "TEXT NOT NULL DEFAULT ''"),
    ],
    "custom_skills": [
        ("triggers", "TEXT NOT NULL DEFAULT '[]'"),
        ("trust_level", "INTEGER NOT NULL DEFAULT 1"),
        ("priority", "INTEGER NOT NULL DEFAULT 10"),
        ("owner_id", "INTEGER"),
    ],
    "analysis_types": [("owner_id", "INTEGER")],
    "reports": [("diamond_layer_ids", "TEXT NOT NULL DEFAULT '[]'")],
    "query_history": [("user_login", "TEXT NOT NULL DEFAULT ''")],
}


def _migrate_user_type_constraint():
    """Amplia o CHECK de users.user_type para papéis adicionados após a criação
    inicial da tabela (ex.: engenheiro_dados). CREATE TABLE IF NOT EXISTS não
    altera constraints de tabelas já existentes. Usa conexão própria para não
    poluir a transação principal de init; idempotente via guarda."""
    conn = get_sync_connection()
    try:
        row = conn.execute(
            "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint "
            "WHERE conname = 'users_user_type_check'"
        ).fetchone()
        current = ""
        if row:
            current = row["def"] if isinstance(row, dict) else row[0]
        if "engenheiro_dados" not in (current or ""):
            conn.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_user_type_check")
            conn.execute(
                "ALTER TABLE users ADD CONSTRAINT users_user_type_check "
                "CHECK (user_type IN ('root','superuser','admin','analista','engenheiro_dados','user'))"
            )
            conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def init_metadata_tables():
    """Create or migrate all internal metadata tables in PostgreSQL.

    Order matters:
      1. CREATE TABLE (all of them, in any order — Postgres handles forward
         references fine when wrapped in a single transaction)
      2. ALTER TABLE column migrations (only when the column is missing)
      3. CREATE INDEX (after every target table exists)
      4. Seed rows (default datamart, default analysis_type)
    """
    conn = get_sync_connection()
    try:
        for stmt in _DDL_STATEMENTS:
            conn.execute(stmt)
        conn.commit()

        for tbl, cols in _COLUMN_MIGRATIONS.items():
            for col_name, col_def in cols:
                if not column_exists(conn, tbl, col_name):
                    conn.execute(f'ALTER TABLE {tbl} ADD COLUMN {col_name} {col_def}')
        conn.commit()

        # Constraint migration: tabelas já existentes não são alteradas por
        # CREATE TABLE IF NOT EXISTS — amplia o CHECK de users.user_type.
        _migrate_user_type_constraint()

        for stmt in _INDEX_STATEMENTS:
            conn.execute(stmt)
        conn.commit()

        # Seed default datamart
        cur = conn.execute("SELECT COUNT(*) AS n FROM datamarts WHERE LOWER(name) = 'default'")
        n = cur.fetchone()
        if (n["n"] if isinstance(n, dict) else n[0]) == 0:
            conn.execute(
                "INSERT INTO datamarts (name, description) VALUES ('default', 'DataMart padrão')"
            )

        # Seed default analysis type
        cur = conn.execute("SELECT COUNT(*) AS n FROM analysis_types")
        n = cur.fetchone()
        if (n["n"] if isinstance(n, dict) else n[0]) == 0:
            conn.execute(
                """
                INSERT INTO analysis_types (name, system_prompt, guardrails_input, guardrails_output)
                VALUES (
                    'Análise Geral',
                    'Você é um analista de dados especialista. Responda em português do Brasil. Gere SQL ANSI compatível com PostgreSQL. Sempre explique os resultados de forma clara e objetiva.',
                    'A consulta deve ser relacionada aos dados disponíveis nas tabelas. Não permita comandos destrutivos (DROP, DELETE, UPDATE, INSERT).',
                    'Apresente os resultados de forma organizada. Inclua observações e insights quando relevante. Formate números com separadores de milhar.'
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def set_favorite_question(user_id: int, question_id: int, param_config: str = "") -> dict:
    """Set a question as favorite. Only one favorite per user."""
    conn = get_sync_connection()
    try:
        # Remove any existing favorite for this user
        conn.execute("UPDATE saved_questions SET is_favorite = 0 WHERE user_id = ?", (user_id,))
        # Set the new favorite
        conn.execute(
            "UPDATE saved_questions SET is_favorite = 1, param_config = ? WHERE id = ? AND user_id = ?",
            (param_config, question_id, user_id),
        )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def unset_favorite_question(user_id: int) -> dict:
    conn = get_sync_connection()
    try:
        conn.execute("UPDATE saved_questions SET is_favorite = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


def get_favorite_question(user_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute(
            "SELECT id, question, label, sql_generated, param_config FROM saved_questions "
            "WHERE user_id = ? AND is_favorite = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DataMart CRUD
# ---------------------------------------------------------------------------

def get_all_datamarts() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM datamarts ORDER BY name")
        dms = []
        for row in cursor.fetchall():
            dm = dict(row)
            tc = conn.execute(
                "SELECT table_name FROM datamart_tables WHERE datamart_id = ? ORDER BY table_name",
                (dm["id"],),
            )
            dm["tables"] = [r[0] for r in tc.fetchall()]
            dms.append(dm)
        return dms
    finally:
        conn.close()


def get_datamart_by_id(dm_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM datamarts WHERE id = ?", (dm_id,)).fetchone()
        if not row:
            return None
        dm = dict(row)
        tc = conn.execute(
            "SELECT table_name FROM datamart_tables WHERE datamart_id = ?", (dm_id,),
        )
        dm["tables"] = [r[0] for r in tc.fetchall()]
        return dm
    finally:
        conn.close()


def get_datamart_by_name(name: str) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM datamarts WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_datamart(name: str, description: str = "") -> dict:
    conn = get_sync_connection()
    try:
        dm_id = _exec_returning_id(
            conn,
            "INSERT INTO datamarts (name, description) VALUES (?, ?)",
            (name, description),
        )
        conn.commit()
        return {"id": dm_id, "name": name, "description": description, "tables": []}
    finally:
        conn.close()


def update_datamart(dm_id: int, **kwargs) -> bool:
    allowed = {"name", "description"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    from datetime import datetime
    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_sync_connection()
    try:
        conn.execute(f"UPDATE datamarts SET {set_clause} WHERE id = ?", (*fields.values(), dm_id))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_datamart(dm_id: int) -> bool:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT name FROM datamarts WHERE id = ?", (dm_id,)).fetchone()
        if row and row[0] == "default":
            return False
        conn.execute("DELETE FROM datamart_tables WHERE datamart_id = ?", (dm_id,))
        conn.execute("DELETE FROM user_datamarts WHERE datamart_id = ?", (dm_id,))
        conn.execute("DELETE FROM datamarts WHERE id = ?", (dm_id,))
        conn.commit()
        return True
    finally:
        conn.close()


def assign_table_to_datamart(dm_id: int, table_name: str) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "INSERT INTO datamart_tables (datamart_id, table_name) VALUES (?, ?) ON CONFLICT (datamart_id, table_name) DO NOTHING",
            (dm_id, table_name),
        )
        conn.commit()
        invalidate_tables_cache()
        return True
    finally:
        conn.close()


def remove_table_from_datamart(dm_id: int, table_name: str) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "DELETE FROM datamart_tables WHERE datamart_id = ? AND table_name = ?",
            (dm_id, table_name),
        )
        conn.commit()
        invalidate_tables_cache()
        return True
    finally:
        conn.close()


def get_user_datamarts(user_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT d.id, d.name, d.description FROM datamarts d
               JOIN user_datamarts ud ON d.id = ud.datamart_id
               WHERE ud.user_id = ? ORDER BY d.name""",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def set_user_datamarts(user_id: int, datamart_ids: list[int]):
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM user_datamarts WHERE user_id = ?", (user_id,))
        for dm_id in datamart_ids:
            conn.execute(
                "INSERT INTO user_datamarts (user_id, datamart_id) VALUES (?, ?) ON CONFLICT (user_id, datamart_id) DO NOTHING",
                (user_id, dm_id),
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# DiamondLayer CRUD (mirrors DataMart, with table ownership)
# ---------------------------------------------------------------------------

def get_all_diamond_layers() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM diamond_layers ORDER BY name")
        layers = []
        for row in cursor.fetchall():
            dl = dict(row)
            tc = conn.execute(
                "SELECT table_name, owner_id FROM diamond_layer_tables WHERE layer_id = ? ORDER BY table_name",
                (dl["id"],),
            )
            dl["tables"] = [{"name": r["table_name"], "owner_id": r["owner_id"]} for r in tc.fetchall()]
            layers.append(dl)
        return layers
    finally:
        conn.close()


def get_diamond_layer_by_id(layer_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM diamond_layers WHERE id = ?", (layer_id,)).fetchone()
        if not row:
            return None
        dl = dict(row)
        tc = conn.execute(
            "SELECT table_name, owner_id FROM diamond_layer_tables WHERE layer_id = ?", (layer_id,),
        )
        dl["tables"] = [{"name": r["table_name"], "owner_id": r["owner_id"]} for r in tc.fetchall()]
        return dl
    finally:
        conn.close()


def get_diamond_layer_by_name(name: str) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM diamond_layers WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_diamond_layer(name: str, description: str = "") -> dict:
    conn = get_sync_connection()
    try:
        layer_id = _exec_returning_id(
            conn,
            "INSERT INTO diamond_layers (name, description) VALUES (?, ?)",
            (name, description),
        )
        conn.commit()
        return {"id": layer_id, "name": name, "description": description, "tables": []}
    finally:
        conn.close()


def update_diamond_layer(layer_id: int, **kwargs) -> bool:
    allowed = {"name", "description"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    from datetime import datetime
    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_sync_connection()
    try:
        conn.execute(f"UPDATE diamond_layers SET {set_clause} WHERE id = ?", (*fields.values(), layer_id))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_diamond_layer(layer_id: int) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM diamond_layer_tables WHERE layer_id = ?", (layer_id,))
        conn.execute("DELETE FROM user_diamond_layers WHERE layer_id = ?", (layer_id,))
        conn.execute("DELETE FROM diamond_layers WHERE id = ?", (layer_id,))
        conn.commit()
        invalidate_tables_cache()
        return True
    finally:
        conn.close()


def assign_table_to_diamond_layer(layer_id: int, table_name: str, owner_id: int | None = None) -> bool:
    """Assigns a table to a DiamondLayer. ``owner_id`` is the user who is taking
    ownership of the table by performing the assignment. On conflict (table
    already in this layer), the existing owner_id is preserved."""
    conn = get_sync_connection()
    try:
        conn.execute(
            "INSERT INTO diamond_layer_tables (layer_id, table_name, owner_id) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT (layer_id, table_name) DO NOTHING",
            (layer_id, table_name, owner_id),
        )
        conn.commit()
        invalidate_tables_cache()
        return True
    finally:
        conn.close()


def remove_table_from_diamond_layer(layer_id: int, table_name: str) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "DELETE FROM diamond_layer_tables WHERE layer_id = ? AND table_name = ?",
            (layer_id, table_name),
        )
        conn.commit()
        invalidate_tables_cache()
        return True
    finally:
        conn.close()


def get_user_diamond_layers(user_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT d.id, d.name, d.description FROM diamond_layers d
               JOIN user_diamond_layers ud ON d.id = ud.layer_id
               WHERE ud.user_id = ? ORDER BY d.name""",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def set_user_diamond_layers(user_id: int, layer_ids: list[int]):
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM user_diamond_layers WHERE user_id = ?", (user_id,))
        for lid in layer_ids:
            conn.execute(
                "INSERT INTO user_diamond_layers (user_id, layer_id) VALUES (?, ?) "
                "ON CONFLICT (user_id, layer_id) DO NOTHING",
                (user_id, lid),
            )
        conn.commit()
    finally:
        conn.close()


def get_tables_for_diamond_layers(layer_ids: list[int]) -> list[str]:
    """Return distinct table names accessible via the given diamond layers."""
    if not layer_ids:
        return []
    conn = get_sync_connection()
    try:
        placeholders = ",".join("?" * len(layer_ids))
        cursor = conn.execute(
            f"SELECT DISTINCT table_name FROM diamond_layer_tables WHERE layer_id IN ({placeholders}) ORDER BY table_name",
            layer_ids,
        )
        return [r[0] for r in cursor.fetchall()]
    finally:
        conn.close()


def get_users_with_access_to_diamond_layers(
    layer_ids: list[int],
    exclude_user_id: int | None = None,
    query: str = "",
    limit: int = 20,
) -> list[dict]:
    """Strict access check: returns active users with access to ALL the given
    diamond_layer_ids. Mirrors get_users_with_access_to_datamarts."""
    if not layer_ids:
        return []
    conn = get_sync_connection()
    try:
        placeholders = ",".join("?" * len(layer_ids))
        params: list = list(layer_ids)
        like = f"%{query.strip().lower()}%" if query and query.strip() else None
        sql = f"""
            SELECT u.id, u.login, u.display_name
            FROM users u
            WHERE u.is_active = 1
              AND (
                SELECT COUNT(DISTINCT ud.layer_id)
                FROM user_diamond_layers ud
                WHERE ud.user_id = u.id AND ud.layer_id IN ({placeholders})
              ) = ?
        """
        params.append(len(set(layer_ids)))
        if exclude_user_id is not None:
            sql += " AND u.id <> ?"
            params.append(exclude_user_id)
        if like:
            sql += " AND (LOWER(u.login) LIKE ? OR LOWER(u.display_name) LIKE ?)"
            params.extend([like, like])
        sql += " ORDER BY u.display_name, u.login LIMIT ?"
        params.append(int(limit))
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_users_with_diamond_layer(layer_id: int) -> list[int]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            "SELECT user_id FROM user_diamond_layers WHERE layer_id = ?",
            (layer_id,),
        )
        return [r[0] for r in cursor.fetchall()]
    finally:
        conn.close()


def set_diamond_layer_users(layer_id: int, user_ids: list[int]):
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM user_diamond_layers WHERE layer_id = ?", (layer_id,))
        for uid in user_ids:
            conn.execute(
                "INSERT INTO user_diamond_layers (user_id, layer_id) VALUES (?, ?) "
                "ON CONFLICT (user_id, layer_id) DO NOTHING",
                (uid, layer_id),
            )
        conn.commit()
    finally:
        conn.close()


def get_users_with_access_to_datamarts(
    datamart_ids: list[int],
    exclude_user_id: int | None = None,
    query: str = "",
    limit: int = 20,
) -> list[dict]:
    """Strict access check: returns active users that have access to ALL the given
    datamart_ids. If *datamart_ids* is empty, returns active users who have access
    to at least one datamart (root has implicit access; we keep the strict policy
    consistent by NOT returning root accounts here).

    Used by the share-by-recipient autocomplete: a recipient must be able to
    re-execute the query, i.e. own every datamart the sender used.
    """
    if not datamart_ids:
        return []
    conn = get_sync_connection()
    try:
        placeholders = ",".join("?" * len(datamart_ids))
        params: list = list(datamart_ids)
        like = f"%{query.strip().lower()}%" if query and query.strip() else None
        sql = f"""
            SELECT u.id, u.login, u.display_name
            FROM users u
            WHERE u.is_active = 1
              AND (
                SELECT COUNT(DISTINCT ud.datamart_id)
                FROM user_datamarts ud
                WHERE ud.user_id = u.id AND ud.datamart_id IN ({placeholders})
              ) = ?
        """
        params.append(len(set(datamart_ids)))
        if exclude_user_id is not None:
            sql += " AND u.id <> ?"
            params.append(exclude_user_id)
        if like:
            sql += " AND (LOWER(u.login) LIKE ? OR LOWER(u.display_name) LIKE ?)"
            params.extend([like, like])
        sql += " ORDER BY u.display_name, u.login LIMIT ?"
        params.append(int(limit))
        cursor = conn.execute(sql, params)
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Shared results (internal share)
# ---------------------------------------------------------------------------

def create_shared_result(
    sender_id: int,
    recipient_id: int,
    question: str,
    sql_generated: str = "",
    datamart_ids: list[int] | None = None,
    label: str = "",
    message: str = "",
) -> dict:
    import json as _json
    conn = get_sync_connection()
    try:
        sid = _exec_returning_id(
            conn,
            """INSERT INTO shared_results
               (sender_id, recipient_id, question, sql_generated, datamart_ids, label, message)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                sender_id,
                recipient_id,
                question,
                sql_generated or "",
                _json.dumps(datamart_ids or []),
                label or "",
                message or "",
            ),
        )
        conn.commit()
        return {"id": sid, "recipient_id": recipient_id}
    finally:
        conn.close()


def list_incoming_shares(recipient_id: int, unread_only: bool = False) -> list[dict]:
    """Return shares received by *recipient_id*, joined with the sender's
    display info, newest first. When *unread_only* is True, only returns shares
    where read_at IS NULL."""
    import json as _json
    conn = get_sync_connection()
    try:
        sql = """
            SELECT s.id, s.sender_id, s.recipient_id, s.question, s.sql_generated,
                   s.datamart_ids, s.label, s.message, s.created_at, s.read_at,
                   u.login AS sender_login, u.display_name AS sender_display_name
            FROM shared_results s
            JOIN users u ON u.id = s.sender_id
            WHERE s.recipient_id = ?
        """
        params: list = [recipient_id]
        if unread_only:
            sql += " AND s.read_at IS NULL"
        sql += " ORDER BY s.created_at DESC"
        rows = []
        for r in conn.execute(sql, params).fetchall():
            d = dict(r)
            try:
                d["datamart_ids"] = _json.loads(d.get("datamart_ids") or "[]")
            except Exception:
                d["datamart_ids"] = []
            rows.append(d)
        return rows
    finally:
        conn.close()


def get_shared_result(share_id: int) -> dict | None:
    import json as _json
    conn = get_sync_connection()
    try:
        row = conn.execute(
            "SELECT * FROM shared_results WHERE id = ?", (share_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["datamart_ids"] = _json.loads(d.get("datamart_ids") or "[]")
        except Exception:
            d["datamart_ids"] = []
        return d
    finally:
        conn.close()


def mark_shared_result_read(share_id: int, recipient_id: int) -> bool:
    """Marks a share as read. Returns True if it belonged to *recipient_id*."""
    conn = get_sync_connection()
    try:
        cur = conn.execute(
            "UPDATE shared_results SET read_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND recipient_id = ? AND read_at IS NULL",
            (share_id, recipient_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_shared_result(share_id: int, recipient_id: int) -> bool:
    """Recipient-only deletion (sender deletion not in scope for Phase 2)."""
    conn = get_sync_connection()
    try:
        cur = conn.execute(
            "DELETE FROM shared_results WHERE id = ? AND recipient_id = ?",
            (share_id, recipient_id),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def get_tables_for_datamarts(datamart_ids: list[int]) -> list[str]:
    """Return distinct table names accessible via the given datamarts."""
    if not datamart_ids:
        return []
    conn = get_sync_connection()
    try:
        placeholders = ",".join("?" * len(datamart_ids))
        cursor = conn.execute(
            f"SELECT DISTINCT table_name FROM datamart_tables WHERE datamart_id IN ({placeholders}) ORDER BY table_name",
            datamart_ids,
        )
        return [r[0] for r in cursor.fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

# In-memory TTL cache for get_all_tables(). Hot path called by /api/tables,
# the agent toolkit, the Data Products scanner, etc. Invalidated explicitly
# on upload / drop / datamart-membership changes via invalidate_tables_cache().
import time as _time
import threading as _threading
_TABLES_CACHE_TTL_SECS = 30.0
_tables_cache: dict = {"data": None, "expires": 0.0}
_tables_cache_lock = _threading.Lock()


def invalidate_tables_cache() -> None:
    """Explicit cache buster called by mutating endpoints (upload, drop,
    datamart membership changes). Cheap and safe to call repeatedly."""
    with _tables_cache_lock:
        _tables_cache["data"] = None
        _tables_cache["expires"] = 0.0


def get_all_tables(use_cache: bool = True) -> list[dict]:
    """List all user data tables (excluding internal metadata).

    Performance-critical: previously did 4×N queries (one per table for
    columns / pk / count / datamarts). Now does **5 batched queries total**,
    independent of how many tables exist:
      1. list user tables (information_schema.tables)
      2. all columns for all those tables (information_schema.columns)
      3. all primary keys for all those tables (pg_index + pg_attribute)
      4. row-count ESTIMATES from pg_class.reltuples (instant; falls back
         to exact COUNT(*) only for tables with reltuples == 0, typically
         freshly created tables that have not been ANALYZEd yet)
      5. datamart memberships in one JOIN

    Result is cached in-memory for ~30 s. Mutating endpoints
    (upload, drop, datamart membership changes) call
    ``invalidate_tables_cache()`` to bust it.
    """
    if use_cache:
        now = _time.monotonic()
        with _tables_cache_lock:
            if _tables_cache["data"] is not None and now < _tables_cache["expires"]:
                return _tables_cache["data"]

    conn = get_sync_connection()
    try:
        # 1. list user tables (excluding metadata)
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
        user_tables = [r["table_name"] for r in rows if r["table_name"] not in INTERNAL_TABLES]
        if not user_tables:
            result: list[dict] = []
            with _tables_cache_lock:
                _tables_cache["data"] = result
                _tables_cache["expires"] = _time.monotonic() + _TABLES_CACHE_TTL_SECS
            return result

        placeholders = ",".join(["?"] * len(user_tables))
        params = tuple(user_tables)

        # 2. all columns for all user tables — one query, group in Python
        col_rows = conn.execute(
            f"SELECT table_name, column_name, data_type, is_nullable "
            f"FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND table_name IN ({placeholders}) "
            f"ORDER BY table_name, ordinal_position",
            params,
        ).fetchall()
        cols_by_table: dict[str, list[dict]] = {}
        for r in col_rows:
            cols_by_table.setdefault(r["table_name"], []).append({
                "name": r["column_name"],
                "type": r["data_type"],
                "notnull": (r["is_nullable"] == "NO"),
                "pk": False,
            })

        # 3. all primary keys for all user tables — one join across catalogs
        pk_rows = conn.execute(
            f"SELECT t.relname AS table_name, a.attname AS column_name "
            f"FROM pg_index i "
            f"JOIN pg_class t ON t.oid = i.indrelid "
            f"JOIN pg_namespace n ON n.oid = t.relnamespace "
            f"JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(i.indkey) "
            f"WHERE n.nspname = 'public' AND i.indisprimary AND t.relname IN ({placeholders})",
            params,
        ).fetchall()
        pk_set_by_table: dict[str, set[str]] = {}
        for r in pk_rows:
            pk_set_by_table.setdefault(r["table_name"], set()).add(r["column_name"])
        for t, cols in cols_by_table.items():
            pk_names = pk_set_by_table.get(t, set())
            for c in cols:
                if c["name"] in pk_names:
                    c["pk"] = True

        # 4. row counts via pg_class.reltuples (instant). reltuples can be 0
        #    for tables that never had ANALYZE run; fall back to exact
        #    COUNT(*) for those — typically freshly uploaded tables.
        rc_rows = conn.execute(
            f"SELECT c.relname AS table_name, GREATEST(c.reltuples, 0)::bigint AS row_count "
            f"FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            f"WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname IN ({placeholders})",
            params,
        ).fetchall()
        rowcount_by_table: dict[str, int] = {r["table_name"]: int(r["row_count"]) for r in rc_rows}
        # Exact fallback ONLY for tables where the estimate is 0 — usually
        # very few, and the count is cheap when the table really is small.
        for t in user_tables:
            if rowcount_by_table.get(t, 0) == 0:
                try:
                    cnt_row = conn.execute(f'SELECT COUNT(*) AS n FROM "{t}"').fetchone()
                    rowcount_by_table[t] = int(cnt_row["n"]) if cnt_row else 0
                except Exception:
                    rowcount_by_table[t] = 0

        # 5. datamart memberships — one JOIN
        dm_rows = conn.execute(
            f"SELECT dt.table_name, d.id AS dm_id, d.name AS dm_name "
            f"FROM datamart_tables dt JOIN datamarts d ON d.id = dt.datamart_id "
            f"WHERE dt.table_name IN ({placeholders}) "
            f"ORDER BY d.name",
            params,
        ).fetchall()
        dms_by_table: dict[str, list[dict]] = {}
        for r in dm_rows:
            dms_by_table.setdefault(r["table_name"], []).append({
                "id": r["dm_id"],
                "name": r["dm_name"],
            })

        # 6. diamond layer memberships — one JOIN
        dl_rows = conn.execute(
            f"SELECT dlt.table_name, dl.id AS layer_id, dl.name AS layer_name, dlt.owner_id "
            f"FROM diamond_layer_tables dlt JOIN diamond_layers dl ON dl.id = dlt.layer_id "
            f"WHERE dlt.table_name IN ({placeholders}) "
            f"ORDER BY dl.name",
            params,
        ).fetchall()
        layers_by_table: dict[str, list[dict]] = {}
        for r in dl_rows:
            layers_by_table.setdefault(r["table_name"], []).append({
                "id": r["layer_id"],
                "name": r["layer_name"],
                "owner_id": r["owner_id"],
            })

        # 7. tabelas tech (TDIA-CodeGen) — marca para o grupo "DataMarts Tech"
        tech_rows = conn.execute(
            f"SELECT table_name FROM codegen_tables WHERE table_name IN ({placeholders})",
            params,
        ).fetchall()
        tech_set = {r["table_name"] for r in tech_rows}

        result = [
            {
                "name": t,
                "columns": cols_by_table.get(t, []),
                "row_count": rowcount_by_table.get(t, 0),
                "datamarts": dms_by_table.get(t, []),
                "diamond_layers": layers_by_table.get(t, []),
                "is_tech": t in tech_set,
                # RLS por linha: a tabela tem coluna "login" (filtro por usuário)?
                "has_login": any((c.get("name") or "").lower() == "login"
                                 for c in cols_by_table.get(t, [])),
            }
            for t in user_tables
        ]
        with _tables_cache_lock:
            _tables_cache["data"] = result
            _tables_cache["expires"] = _time.monotonic() + _TABLES_CACHE_TTL_SECS
        return result
    finally:
        conn.close()


def get_tables_filtered(table_names: list[str]) -> list[dict]:
    """Like get_all_tables but filtered to specific table names."""
    all_tables = get_all_tables()
    if not table_names:
        return all_tables
    name_set = set(table_names)
    return [t for t in all_tables if t["name"] in name_set]


def get_table_schema_text(table_names: list[str] | None = None) -> str:
    """Return a textual description of tables for agent context."""
    tables = get_all_tables()
    if table_names:
        name_set = set(table_names)
        tables = [t for t in tables if t["name"] in name_set]
    if not tables:
        return "Nenhuma tabela de dados encontrada no banco."
    parts = []
    for t in tables:
        cols = ", ".join(f'{c["name"]} ({c["type"]})' for c in t["columns"])
        parts.append(f'Tabela "{t["name"]}" ({t["row_count"]} registros): {cols}')
    return "\n".join(parts)


def get_tables_with_login_column(table_names: list[str] | None = None) -> list[str]:
    """Return names of user data tables that have a column named 'login' (case-insensitive).
    Used for row-level security: queries on these tables must be filtered by user login."""
    conn = get_sync_connection()
    try:
        if table_names:
            candidates = table_names
        else:
            cursor = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
                "ORDER BY table_name"
            )
            candidates = [r["table_name"] for r in cursor.fetchall() if r["table_name"] not in INTERNAL_TABLES]
        if not candidates:
            return []
        # One query for all candidates: tables having a column literally named 'login'.
        placeholders = ",".join(["?"] * len(candidates))
        rows = conn.execute(
            f"SELECT DISTINCT table_name FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND LOWER(column_name) = 'login' "
            f"AND table_name IN ({placeholders})",
            tuple(candidates),
        ).fetchall()
        return [r["table_name"] for r in rows]
    finally:
        conn.close()
 

# Teto de tempo para QUALQUER consulta de leitura (chat, exec, reportes). Sem ele, um
# SQL pesado gerado pelo LLM (ex.: JOIN/GROUP BY na cuboprepagopf ~4M linhas) roda
# indefinidamente, bloqueia o worker e a conexão acaba caindo no navegador como o
# críptico "Failed to fetch". Excedido → QueryCanceled, devolvido como erro claro.
_READONLY_STMT_TIMEOUT_MS = max(1000, int(os.getenv("QUERY_STATEMENT_TIMEOUT_SECONDS", "60")) * 1000)


def _fix_pg_numeric_funcs(sql: str) -> str:
    """Blinda contra ``ROUND(double precision, N)``/``TRUNC(double precision, N)``, que
    NÃO existem no PostgreSQL (o ``ROUND`` de 2 args só aceita ``numeric``). Como
    ``numeric / double precision`` resulta em ``double precision``, o LLM castar só um
    operando não basta — o argumento INTEIRO precisa virar ``numeric``. Reescreve via AST
    (sqlglot) todo ``ROUND``/``TRUNC`` de 2 args para envolver o 1º argumento em
    ``::numeric``. Determinístico e cobre todos os caminhos de leitura (chat, exec,
    reportes), sem depender de o modelo acertar o cast.

    Fail-safe: só age se houver ``round(``/``trunc(`` (evita custo no caso comum) e, em
    QUALQUER erro de parse/serialização, devolve o SQL original inalterado."""
    if not sql:
        return sql
    low = sql.lower()
    if "round(" not in low and "trunc(" not in low:
        return sql
    try:
        import sqlglot
        from sqlglot import exp
        tree = sqlglot.parse_one(sql, read="postgres")
        if tree is None:
            return sql
        flag = {"changed": False}

        def _wrap(node):
            if isinstance(node, (exp.Round, exp.Trunc)) and node.args.get("decimals") is not None:
                arg = node.this
                # já castado p/ numeric/decimal no topo? não re-castar
                already = (isinstance(arg, exp.Cast) and arg.to is not None
                           and arg.to.this == exp.DataType.Type.DECIMAL)
                if arg is not None and not already:
                    node.set("this", exp.Cast(this=arg.copy(), to=exp.DataType.build("numeric")))
                    flag["changed"] = True
            return node

        fixed = tree.transform(_wrap)
        if not flag["changed"]:
            return sql
        return fixed.sql(dialect="postgres")
    except Exception:
        return sql


def execute_readonly_sql(sql: str) -> dict:
    """Execute a read-only SQL statement and return results."""
    validation_error = _validate_select_only_sql(sql)
    if validation_error:
        return {"error": validation_error, "error_type": "ValidationError"}

    # Blindagem determinística contra ROUND/TRUNC(double precision, N) — ver
    # _fix_pg_numeric_funcs. Aplicada após a validação (que olha o SQL original) e antes
    # de executar; fail-safe devolve o SQL original se o sqlglot não parsear.
    sql = _fix_pg_numeric_funcs(sql)

    # Teto dinâmico (Configurações › Ajustes, Root); fallback p/ o env/default.
    try:
        from app.core.app_settings import get_setting
        timeout_ms = max(1000, int(get_setting("query_statement_timeout_seconds") or 60) * 1000)
    except Exception:
        timeout_ms = _READONLY_STMT_TIMEOUT_MS

    conn = get_sync_connection()
    try:
        # SET LOCAL = escopo da transação (rollback ao devolver ao pool reseta), então
        # não vaza o teto para a próxima consulta na mesma conexão do pool.
        try:
            conn.execute(f"SET LOCAL statement_timeout = {timeout_ms}")
        except Exception:
            pass
        cursor = conn.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        # cursor.fetchall() returns HybridRow objects (db_engine's row factory).
        # HybridRow is a Mapping, so iterating it yields KEYS (column names),
        # not values — ``dict(zip(columns, row))`` would therefore produce
        # ``{"col": "col"}`` instead of ``{"col": value}``. Use ``dict(row)``
        # which goes through the Mapping protocol and reads __getitem__ for
        # each key. Defensive fallback for tuple/list rows kept in case a
        # caller swaps the factory.
        raw_rows = cursor.fetchall()
        if raw_rows and not isinstance(raw_rows[0], (list, tuple)):
            rows = [dict(row) for row in raw_rows]
        else:
            rows = [dict(zip(columns, row)) for row in raw_rows]
        return {"columns": columns, "rows": rows, "row_count": len(rows)}
    except Exception as exc:
        # Expõe o erro REAL do banco (antes era mascarado por uma mensagem
        # genérica). Habilita troubleshooting, auto-correção e registro de
        # falhas com o motivo exato (ex.: "function round(double precision,
        # integer) does not exist").
        msg = str(exc).strip()
        etype = type(exc).__name__
        # Timeout: mensagem acionável em vez do "canceling statement due to statement
        # timeout" do Postgres — e error_type estável para registro/UX.
        if etype == "QueryCanceled" or "statement timeout" in msg.lower():
            secs = timeout_ms // 1000
            return {
                "error": (f"A consulta excedeu o tempo limite de {secs}s. Refine o escopo "
                          "(adicione filtros, agregue, ou reduza o número de tabelas/linhas) "
                          "e tente de novo."),
                "error_type": "QueryTimeout",
            }
        return {
            "error": msg or "Erro ao executar consulta de leitura.",
            "error_type": etype,
        }
    finally:
        conn.close()


def drop_user_table(table_name: str) -> dict:
    """Drop a user data table. Internal metadata tables are protected."""
    if table_name in INTERNAL_TABLES:
        return {"error": f"A tabela '{table_name}' é interna e não pode ser excluída."}
    if not _is_safe_identifier(table_name):
        return {"error": "Nome de tabela inválido."}
    conn = get_sync_connection()
    try:
        if not table_exists(conn, table_name):
            return {"error": f"Tabela '{table_name}' não encontrada."}
        conn.execute(f'DROP TABLE "{table_name}"')
        conn.execute("DELETE FROM datamart_tables WHERE table_name = ?", (table_name,))
        conn.execute("DELETE FROM diamond_layer_tables WHERE table_name = ?", (table_name,))
        conn.commit()
        invalidate_tables_cache()
        return {"success": True, "message": f"Tabela '{table_name}' excluída."}
    except Exception:
        return {"error": "Erro ao excluir tabela."}
    finally:
        conn.close()


def rename_user_table(old_name: str, new_name: str) -> dict:
    """Rename a user data table (Postgres ALTER TABLE).

    Returns ``{"success": True}`` on success, otherwise ``{"error": "..."}``.
    Also rewrites references in ``datamart_tables`` and
    ``diamond_layer_tables`` so existing memberships survive the rename.
    """
    if old_name == new_name:
        return {"success": True, "message": "Nome inalterado."}
    if old_name in INTERNAL_TABLES or new_name in INTERNAL_TABLES:
        return {"error": "Nome de tabela reservado."}
    if not _is_safe_identifier(old_name) or not _is_safe_identifier(new_name):
        return {"error": "Nome de tabela inválido."}
    conn = get_sync_connection()
    try:
        if not table_exists(conn, old_name):
            return {"error": f"Tabela '{old_name}' não encontrada."}
        if table_exists(conn, new_name):
            return {"error": f"Tabela '{new_name}' já existe."}
        conn.execute(f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"')
        conn.execute(
            "UPDATE datamart_tables SET table_name = ? WHERE table_name = ?",
            (new_name, old_name),
        )
        conn.execute(
            "UPDATE diamond_layer_tables SET table_name = ? WHERE table_name = ?",
            (new_name, old_name),
        )
        conn.commit()
        invalidate_tables_cache()
        return {"success": True, "old_name": old_name, "new_name": new_name}
    except Exception as e:
        return {"error": f"Erro ao renomear: {str(e)[:200]}"}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SKILL.md — Frontmatter Parser & Progressive Disclosure
# ---------------------------------------------------------------------------

_STOPWORDS_PT = {
    "para", "como", "quando", "esta", "esse", "essa", "cada", "mais", "menos",
    "usar", "skill", "dados", "sobre", "pode", "deve", "será", "sido", "foram",
    "também", "muito", "todo", "toda", "todos", "todas", "onde", "qual", "quais",
    "isso", "isto", "aqui", "então", "pela", "pelo", "pelas", "pelos", "com",
    "sem", "nos", "nas", "dos", "das", "que", "uma", "uns", "umas",
}


def _parse_skill_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter from SKILL.md content.
    Returns {'frontmatter': dict, 'body': str}.
    If no frontmatter, returns empty dict + full content as body."""
    if not content or not content.strip().startswith("---"):
        return {"frontmatter": {}, "body": content or ""}
    try:
        import yaml
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
        if not match:
            return {"frontmatter": {}, "body": content}
        fm = yaml.safe_load(match.group(1)) or {}
        return {"frontmatter": fm, "body": match.group(2).strip()}
    except Exception:
        return {"frontmatter": {}, "body": content}


def _auto_extract_triggers(name: str, description: str) -> list[str]:
    """Generate trigger keywords from name and description when none provided."""
    words = set()
    for text in [name, description]:
        for word in re.findall(r'\b\w{4,}\b', (text or "").lower()):
            if word not in _STOPWORDS_PT:
                words.add(word)
    return sorted(words)[:15]


def _resolve_skill_triggers(name: str, description: str, content: str,
                            explicit_triggers: list | None = None) -> str:
    """Resolve triggers: explicit > frontmatter > auto-extracted. Returns JSON string."""
    import json as _json

    # 1. Explicit triggers (from API/form)
    if explicit_triggers:
        return _json.dumps(explicit_triggers, ensure_ascii=False)

    # 2. From frontmatter
    parsed = _parse_skill_frontmatter(content)
    fm_triggers = parsed["frontmatter"].get("triggers")
    if fm_triggers and isinstance(fm_triggers, list):
        return _json.dumps(fm_triggers, ensure_ascii=False)

    # 3. Auto-extract
    auto = _auto_extract_triggers(name, description)
    return _json.dumps(auto, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Custom Skills CRUD
# ---------------------------------------------------------------------------

def get_all_skills() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM custom_skills ORDER BY name")
        skills = []
        for r in cursor.fetchall():
            s = dict(r)
            # Parse triggers JSON → list
            try:
                s["triggers"] = json.loads(s.get("triggers") or "[]")
            except Exception:
                s["triggers"] = []
            skills.append(s)
        return skills
    finally:
        conn.close()


def get_active_skills() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM custom_skills WHERE is_active = 1 ORDER BY name")
        skills = []
        for r in cursor.fetchall():
            s = dict(r)
            try:
                s["triggers"] = json.loads(s.get("triggers") or "[]")
            except Exception:
                s["triggers"] = []
            skills.append(s)
        return skills
    finally:
        conn.close()


def get_skill_by_id(skill_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM custom_skills WHERE id = ?", (skill_id,)).fetchone()
        if not row:
            return None
        s = dict(row)
        try:
            s["triggers"] = json.loads(s.get("triggers") or "[]")
        except Exception:
            s["triggers"] = []
        return s
    finally:
        conn.close()


def create_skill(name: str, description: str, content: str, created_by: str = "",
                 triggers: list | None = None, owner_id: int | None = None) -> dict:
    triggers_json = _resolve_skill_triggers(name, description, content, triggers)
    # Extract trust_level and priority from frontmatter if present
    parsed = _parse_skill_frontmatter(content)
    fm = parsed["frontmatter"]
    trust_level = int(fm.get("trust_level", 1))
    priority = int(fm.get("priority", 10))

    conn = get_sync_connection()
    try:
        sid = _exec_returning_id(
            conn,
            "INSERT INTO custom_skills (name, description, content, triggers, trust_level, priority, created_by, owner_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (name, description, content, triggers_json, trust_level, priority, created_by, owner_id),
        )
        conn.commit()
        return {"id": sid, "name": name}
    finally:
        conn.close()


def update_skill(skill_id: int, **kwargs) -> bool:
    allowed = {"name", "description", "content", "is_active", "triggers", "trust_level", "priority"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False

    # If content changed, re-resolve triggers (unless triggers explicitly provided)
    if "content" in fields and "triggers" not in fields:
        existing = get_skill_by_id(skill_id)
        if existing:
            name = fields.get("name", existing["name"])
            desc = fields.get("description", existing["description"])
            fields["triggers"] = _resolve_skill_triggers(name, desc, fields["content"])

    # Serialize triggers list → JSON string if needed
    if "triggers" in fields and isinstance(fields["triggers"], list):
        fields["triggers"] = json.dumps(fields["triggers"], ensure_ascii=False)

    from datetime import datetime
    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_sync_connection()
    try:
        conn.execute(f"UPDATE custom_skills SET {set_clause} WHERE id = ?", (*fields.values(), skill_id))
        conn.commit()
        return True
    finally:
        conn.close()


def delete_skill(skill_id: int) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM custom_skills WHERE id = ?", (skill_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Saved Questions
# ---------------------------------------------------------------------------

def _strip_sql_limit(sql: str) -> str:
    """Remove trailing LIMIT clause from SQL so the saved version is reusable
    with any limit applied at execution time."""
    if not sql:
        return sql
    return re.sub(r'\s+LIMIT\s+\d+\s*;?\s*$', '', sql.strip(), flags=re.IGNORECASE).strip()


def get_saved_questions(user_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            "SELECT id, question, label, sql_generated, is_favorite, param_config, created_at "
            "FROM saved_questions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def create_saved_question(user_id: int, question: str, label: str = "", sql_generated: str = "") -> dict:
    sql_generated = _strip_sql_limit(sql_generated)
    conn = get_sync_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM saved_questions WHERE user_id = ? AND question = ?",
            (user_id, question),
        ).fetchone()
        if existing:
            # Atualizar o SQL se a pergunta já existe e o novo SQL não é vazio
            if sql_generated:
                conn.execute(
                    "UPDATE saved_questions SET sql_generated = ? WHERE id = ?",
                    (sql_generated, existing[0]),
                )
                conn.commit()
            return {"id": existing[0], "question": question, "label": label, "duplicate": True}

        sid = _exec_returning_id(
            conn,
            "INSERT INTO saved_questions (user_id, question, label, sql_generated) VALUES (?, ?, ?, ?)",
            (user_id, question, label, sql_generated),
        )
        conn.commit()
        return {"id": sid, "question": question, "label": label}
    finally:
        conn.close()


def delete_saved_question(question_id: int, user_id: int) -> bool:
    """Delete only if the question belongs to the user."""
    conn = get_sync_connection()
    try:
        conn.execute(
            "DELETE FROM saved_questions WHERE id = ? AND user_id = ?",
            (question_id, user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()

def get_all_saved_questions_with_user() -> list[dict]:
    """Return all saved questions with user display_name (for admin view)."""
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT sq.id, sq.question, sq.label, sq.sql_generated, sq.created_at,
                      u.id as user_id, u.login, u.display_name
               FROM saved_questions sq
               JOIN users u ON sq.user_id = u.id
               ORDER BY sq.created_at DESC"""
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_saved_questions_with_user(user_id: int) -> list[dict]:
    """Return saved questions for a specific user, with user info."""
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT sq.id, sq.question, sq.label, sq.sql_generated, sq.created_at,
                      u.id as user_id, u.login, u.display_name
               FROM saved_questions sq
               JOIN users u ON sq.user_id = u.id
               WHERE sq.user_id = ?
               ORDER BY sq.created_at DESC""",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def import_saved_questions(user_id: int, rows: list[dict]) -> dict:
    """Import saved questions from list of dicts with 'question' and optional 'label'."""
    conn = get_sync_connection()
    created, skipped, errors = [], [], []
    try:
        for row in rows:
            question = str(row.get("question", "")).strip()
            label = str(row.get("label", "")).strip()
            sql_gen = str(row.get("sql_generated", row.get("sql", ""))).strip()
            if label == "nan":
                label = ""
            if sql_gen == "nan":
                sql_gen = ""
            sql_gen = _strip_sql_limit(sql_gen)
            if not question or len(question) < 3:
                errors.append(f"Pergunta vazia ou curta: '{question[:30]}'")
                continue
            existing = conn.execute(
                "SELECT id FROM saved_questions WHERE user_id = ? AND question = ?",
                (user_id, question),
            ).fetchone()
            if existing:
                skipped.append(question[:50])
                continue
            conn.execute(
                "INSERT INTO saved_questions (user_id, question, label, sql_generated) VALUES (?, ?, ?, ?)",
                (user_id, question, label, sql_gen),
            )
            created.append(question[:50])
        conn.commit()
        return {"created": len(created), "skipped": len(skipped), "errors": errors, "total": len(rows)}
    finally:
        conn.close()


def update_saved_question_label(question_id: int, user_id: int, label: str) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "UPDATE saved_questions SET label = ? WHERE id = ? AND user_id = ?",
            (label, question_id, user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Saved Visions
# ---------------------------------------------------------------------------

def get_visions(user_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            "SELECT id, question, sql_generated, label, created_at "
            "FROM saved_visions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_all_visions_with_user() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT sv.id, sv.question, sv.sql_generated, sv.label, sv.created_at,
                      u.id as user_id, u.login, u.display_name
               FROM saved_visions sv
               JOIN users u ON sv.user_id = u.id
               ORDER BY sv.created_at DESC"""
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def get_visions_with_user(user_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT sv.id, sv.question, sv.sql_generated, sv.label, sv.created_at,
                      u.id as user_id, u.login, u.display_name
               FROM saved_visions sv
               JOIN users u ON sv.user_id = u.id
               WHERE sv.user_id = ?
               ORDER BY sv.created_at DESC""",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def create_vision(user_id: int, question: str, sql_generated: str = "", label: str = "") -> dict:
    conn = get_sync_connection()
    try:
        sid = _exec_returning_id(
            conn,
            "INSERT INTO saved_visions (user_id, question, sql_generated, label) VALUES (?, ?, ?, ?)",
            (user_id, question, sql_generated, label),
        )
        conn.commit()
        return {"id": sid, "question": question, "label": label}
    finally:
        conn.close()


def delete_vision(vision_id: int, user_id: int) -> bool:
    conn = get_sync_connection()
    try:
        if user_id == 0:
            conn.execute("DELETE FROM saved_visions WHERE id = ?", (vision_id,))
        else:
            conn.execute(
                "DELETE FROM saved_visions WHERE id = ? AND user_id = ?",
                (vision_id, user_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def update_vision_label(vision_id: int, user_id: int, label: str) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "UPDATE saved_visions SET label = ? WHERE id = ? AND user_id = ?",
            (label, vision_id, user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def update_vision_meta(vision_id: int, user_id: int, label: str, question: str | None = None) -> bool:
    """Update a saved vision's label (always) and question (only when provided).

    ``user_id == 0`` bypasses the ownership filter (admin/root), mirroring
    ``delete_vision``.
    """
    conn = get_sync_connection()
    try:
        sets = ["label = ?"]
        params: list = [label]
        if question is not None:
            sets.append("question = ?")
            params.append(question)
        where = "id = ?"
        params.append(vision_id)
        if user_id != 0:
            where += " AND user_id = ?"
            params.append(user_id)
        conn.execute(
            f"UPDATE saved_visions SET {', '.join(sets)} WHERE {where}",
            tuple(params),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def import_visions(user_id: int, rows: list[dict]) -> dict:
    conn = get_sync_connection()
    created, skipped, errors = [], [], []
    try:
        for row in rows:
            question = str(row.get("question", "")).strip()
            label = str(row.get("label", "")).strip()
            sql_gen = str(row.get("sql_generated", "")).strip()
            if label == "nan": label = ""
            if sql_gen == "nan": sql_gen = ""
            if not question or len(question) < 3:
                errors.append(f"Pergunta vazia: '{question[:30]}'")
                continue
            existing = conn.execute(
                "SELECT id FROM saved_visions WHERE user_id = ? AND question = ?",
                (user_id, question),
            ).fetchone()
            if existing:
                skipped.append(question[:50])
                continue
            conn.execute(
                "INSERT INTO saved_visions (user_id, question, sql_generated, label) VALUES (?, ?, ?, ?)",
                (user_id, question, sql_gen, label),
            )
            created.append(question[:50])
        conn.commit()
        return {"created": len(created), "skipped": len(skipped), "errors": errors, "total": len(rows)}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Cockpit Tiles
# ---------------------------------------------------------------------------

def init_cockpit_table(conn: DialectConnection):
    """Idempotent — kept for callers that opportunistically initialise the
    cockpit table outside of init_metadata_tables."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cockpit_tiles (
            id BIGSERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            vision_id INTEGER NOT NULL,
            chart_type TEXT NOT NULL DEFAULT 'bar',
            x_field TEXT NOT NULL DEFAULT '',
            y_field TEXT NOT NULL DEFAULT '',
            agg TEXT NOT NULL DEFAULT 'sum',
            position INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (vision_id) REFERENCES saved_visions(id) ON DELETE CASCADE
        )
    """)


def get_cockpit_tiles(user_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            """SELECT ct.id, ct.vision_id, ct.chart_type, ct.x_field, ct.y_field,
                      ct.agg, ct.position, sv.question, sv.sql_generated, sv.label
               FROM cockpit_tiles ct
               JOIN saved_visions sv ON ct.vision_id = sv.id
               WHERE ct.user_id = ?
               ORDER BY ct.position ASC""",
            (user_id,),
        )
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()


def add_cockpit_tile(user_id: int, vision_id: int, chart_type: str = "bar",
                     x_field: str = "", y_field: str = "", agg: str = "sum") -> dict:
    conn = get_sync_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM cockpit_tiles WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        if count >= 6:
            raise ValueError("Limite de 6 tiles atingido")
        max_pos = conn.execute(
            "SELECT COALESCE(MAX(position), 0) FROM cockpit_tiles WHERE user_id = ?", (user_id,)
        ).fetchone()[0]
        position = max_pos + 1
        tid = _exec_returning_id(
            conn,
            "INSERT INTO cockpit_tiles (user_id, vision_id, chart_type, x_field, y_field, agg, position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, vision_id, chart_type, x_field, y_field, agg, position),
        )
        conn.commit()
        return {"id": tid, "position": position}
    finally:
        conn.close()


def update_cockpit_tile(tile_id: int, user_id: int, **kwargs) -> bool:
    allowed = {"chart_type", "x_field", "y_field", "agg", "position"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}
    if not fields:
        return False
    conn = get_sync_connection()
    try:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE cockpit_tiles SET {set_clause} WHERE id = ? AND user_id = ?",
            (*fields.values(), tile_id, user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_cockpit_tile(tile_id: int, user_id: int) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "DELETE FROM cockpit_tiles WHERE id = ? AND user_id = ?", (tile_id, user_id)
        )
        conn.commit()
        return True
    finally:
        conn.close()


def reorder_cockpit_tiles(user_id: int, tile_ids: list[int]) -> bool:
    conn = get_sync_connection()
    try:
        for pos, tid in enumerate(tile_ids, 1):
            conn.execute(
                "UPDATE cockpit_tiles SET position = ? WHERE id = ? AND user_id = ?",
                (pos, tid, user_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()

def get_all_json_sources() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM json_sources ORDER BY name")
        return [dict(r) for r in cursor.fetchall()]
    finally:
        conn.close()
 
 
def get_json_source_by_id(source_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM json_sources WHERE id = ?", (source_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
 
 
def create_json_source(
    name: str,
    url_template: str,
    table_name: str,
    json_path: str = "",
    date_format: str = "yyyy-MM-dd",
    http_headers: str = "{}",
    append_mode: int = 0,
    datamart_id: int | None = None,
    description: str = "",
) -> dict:
    conn = get_sync_connection()
    try:
        sid = _exec_returning_id(
            conn,
            """INSERT INTO json_sources
               (name, url_template, table_name, json_path, date_format,
                http_headers, append_mode, datamart_id, description)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (name, url_template, table_name, json_path, date_format,
             http_headers, append_mode, datamart_id, description),
        )
        conn.commit()
        return get_json_source_by_id(sid)
    finally:
        conn.close()
 
 
def update_json_source(source_id: int, **kwargs) -> bool:
    allowed = {
        "name", "url_template", "table_name", "json_path", "date_format",
        "http_headers", "append_mode", "datamart_id", "description",
        "last_imported_at", "last_rows_imported",
    }
    from datetime import datetime as _dt
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return False
    fields["updated_at"] = _dt.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    conn = get_sync_connection()
    try:
        conn.execute(
            f"UPDATE json_sources SET {set_clause} WHERE id = ?",
            (*fields.values(), source_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
 
 
def delete_json_source(source_id: int) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM json_sources WHERE id = ?", (source_id,))
        conn.commit()
        return True
    finally:
        conn.close()

def _build_nomenclature(domain: str, artifact_type: str, name: str, version: str) -> str:
    """Build ODPS nomenclature: <domain>.<type>.<name>.<version>"""
    d = re.sub(r'[^a-z0-9]', '_', (domain or 'geral').lower()).strip('_')
    t = re.sub(r'[^a-z0-9]', '_', (artifact_type or 'dataset').lower()).strip('_')
    n = re.sub(r'[^a-z0-9]', '_', (name or 'unnamed').lower()).strip('_')
    v = 'v' + (version or '1').split('.')[0]
    return f"{d}.{t}.{n}.{v}"
 
 
def _parse_dp_json_fields(p: dict) -> dict:
    """Parse JSON string fields in a data product row to Python objects."""
    for field in ("consumers", "compliance", "tags", "artifacts",
                  "input_ports", "output_ports", "quality_rules"):
        try:
            p[field] = json.loads(p.get(field) or ("[]" if field != "tags" else "{}"))
        except (json.JSONDecodeError, TypeError):
            p[field] = [] if field != "tags" else {}
    return p
 
 
def get_all_data_products() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT * FROM data_products ORDER BY domain, name")
        return [_parse_dp_json_fields(dict(r)) for r in cursor.fetchall()]
    finally:
        conn.close()
 
 
def get_data_product_by_id(product_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM data_products WHERE id = ?", (product_id,)).fetchone()
        return _parse_dp_json_fields(dict(row)) if row else None
    finally:
        conn.close()
 
 
def create_data_product(data: dict) -> dict:
    conn = get_sync_connection()
    try:
        name = data.get("name", "").strip()
        if not name:
            raise ValueError("Nome obrigatório.")
 
        artifacts = data.get("artifacts", [])
        art_type = "dataset"
        if artifacts and isinstance(artifacts, list) and len(artifacts) > 0:
            art_type = artifacts[0].get("type", "dataset") if isinstance(artifacts[0], dict) else "dataset"
 
        nomenclature = _build_nomenclature(
            data.get("domain", ""), art_type, name, data.get("version", "1.0.0"),
        )
 
        json_fields = {}
        for f in ("consumers", "compliance", "tags", "artifacts",
                  "input_ports", "output_ports", "quality_rules"):
            val = data.get(f, [] if f != "tags" else {})
            json_fields[f] = json.dumps(val, ensure_ascii=False) if not isinstance(val, str) else val
 
        pid = _exec_returning_id(
            conn,
            """INSERT INTO data_products
               (name, display_name, version, status, domain,
                purpose, business_value, consumers,
                owner_team, owner_email, owner_role,
                classification, compliance, tags,
                artifacts, input_ports, output_ports,
                quality_rules, sla_freshness, sla_availability,
                value_layer, consumption_type, nomenclature, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                name,
                data.get("display_name", name),
                data.get("version", "1.0.0"),
                data.get("status", "draft"),
                data.get("domain", ""),
                data.get("purpose", ""),
                data.get("business_value", ""),
                json_fields["consumers"],
                data.get("owner_team", ""),
                data.get("owner_email", ""),
                data.get("owner_role", "data product owner"),
                data.get("classification", "internal"),
                json_fields["compliance"],
                json_fields["tags"],
                json_fields["artifacts"],
                json_fields["input_ports"],
                json_fields["output_ports"],
                json_fields["quality_rules"],
                data.get("sla_freshness", ""),
                data.get("sla_availability", ""),
                data.get("value_layer", "refined"),
                data.get("consumption_type", "analytical"),
                nomenclature,
                data.get("created_by", ""),
            ),
        )
        conn.commit()
        return get_data_product_by_id(pid)
    finally:
        conn.close()
 
 
def update_data_product(product_id: int, data: dict) -> bool:
    from datetime import datetime as _dt
    conn = get_sync_connection()
    try:
        existing = conn.execute("SELECT * FROM data_products WHERE id = ?", (product_id,)).fetchone()
        if not existing:
            return False
 
        allowed_scalar = {
            "name", "display_name", "version", "status", "domain",
            "purpose", "business_value",
            "owner_team", "owner_email", "owner_role",
            "classification",
            "sla_freshness", "sla_availability",
            "value_layer", "consumption_type",
        }
        json_field_names = {"consumers", "compliance", "tags", "artifacts",
                            "input_ports", "output_ports", "quality_rules"}
 
        fields = {}
        for k, v in data.items():
            if k in allowed_scalar and v is not None:
                fields[k] = v
            elif k in json_field_names and v is not None:
                fields[k] = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
 
        if not fields:
            return False
 
        # Rebuild nomenclature
        name = fields.get("name", existing["name"])
        domain = fields.get("domain", existing["domain"])
        version = fields.get("version", existing["version"])
        arts_raw = fields.get("artifacts", existing["artifacts"])
        try:
            arts = json.loads(arts_raw) if isinstance(arts_raw, str) else arts_raw
        except Exception:
            arts = []
        art_type = "dataset"
        if arts and isinstance(arts, list) and len(arts) > 0:
            art_type = arts[0].get("type", "dataset") if isinstance(arts[0], dict) else "dataset"
        fields["nomenclature"] = _build_nomenclature(domain, art_type, name, version)
        fields["updated_at"] = _dt.utcnow().isoformat()
 
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(
            f"UPDATE data_products SET {set_clause} WHERE id = ?",
            (*fields.values(), product_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()
 
 
def delete_data_product(product_id: int) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM data_products WHERE id = ?", (product_id,))
        conn.commit()
        return True
    finally:
        conn.close()
 
 
def transition_data_product_status(product_id: int, new_status: str) -> dict | None:
    """Lifecycle: draft → active → deprecated → retired (com rollback deprecated → active)."""
    valid_transitions = {
        "draft": ["active"],
        "active": ["deprecated"],
        "deprecated": ["active", "retired"],
        "retired": [],
    }
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT status FROM data_products WHERE id = ?", (product_id,)).fetchone()
        if not row:
            return None
        current = row[0]
        allowed = valid_transitions.get(current, [])
        if new_status not in allowed:
            return {"error": f"Transição inválida: {current} → {new_status}. Permitidas: {allowed}"}
        from datetime import datetime as _dt
        conn.execute(
            "UPDATE data_products SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, _dt.utcnow().isoformat(), product_id),
        )
        conn.commit()
        return get_data_product_by_id(product_id)
    finally:
        conn.close()
 
 
def validate_data_product(product_id: int) -> dict:
    """Checklist de governança ODPS: owner, outputPort, contrato, versão, SLA."""
    p = get_data_product_by_id(product_id)
    if not p:
        return {"valid": False, "errors": ["Produto não encontrado."], "checks_passed": 0, "checks_total": 5}
    checks = []
    if not p.get("owner_team"):
        checks.append("owner: não definido")
    if not p.get("output_ports") or len(p["output_ports"]) == 0:
        checks.append("outputPort: nenhum definido")
    has_contract = any(
        (port.get("contractId") if isinstance(port, dict) else False)
        for port in (p.get("output_ports") or [])
    )
    if not has_contract:
        checks.append("contrato: nenhum output port possui contractId")
    if not p.get("version") or p["version"] == "0.0.0":
        checks.append("versão: não definida")
    if not p.get("sla_freshness") and not p.get("sla_availability"):
        checks.append("SLA: nenhum SLA definido")
    return {
        "valid": len(checks) == 0,
        "checks_passed": 5 - len(checks),
        "checks_total": 5,
        "errors": checks,
        "product_id": product_id,
        "status": p.get("status"),
    }



# ---------------------------------------------------------------------------
# Reportes (executive reports — banded layout)
# ---------------------------------------------------------------------------

def _row_to_report(row) -> dict:
    """Hidrata uma linha bruta de `reports` em dict pronto pra API."""
    if row is None:
        return None
    d = dict(row)
    try:
        d["datamart_ids"] = json.loads(d.get("datamart_ids") or "[]")
    except Exception:
        d["datamart_ids"] = []
    try:
        d["diamond_layer_ids"] = json.loads(d.get("diamond_layer_ids") or "[]")
    except Exception:
        d["diamond_layer_ids"] = []
    try:
        d["definition"] = json.loads(d.get("definition") or "{}")
    except Exception:
        d["definition"] = {}
    return d


def create_report(
    owner_id: int,
    name: str,
    description: str = "",
    question: str = "",
    sql_generated: str = "",
    datamart_ids: list[int] | None = None,
    diamond_layer_ids: list[int] | None = None,
    definition: dict | None = None,
) -> dict:
    conn = get_sync_connection()
    try:
        rid = _exec_returning_id(
            conn,
            "INSERT INTO reports (owner_id, name, description, question, sql_generated, "
            "datamart_ids, diamond_layer_ids, definition) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                owner_id,
                name,
                description or "",
                question or "",
                sql_generated or "",
                json.dumps(datamart_ids or []),
                json.dumps(diamond_layer_ids or []),
                json.dumps(definition or {}),
            ),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (rid,)).fetchone()
        return _row_to_report(row)
    finally:
        conn.close()


def update_report(report_id: int, fields: dict) -> dict | None:
    """Atualização parcial. Aceita subset de:
    name, description, question, sql_generated, datamart_ids, definition, status."""
    if not fields:
        return get_report(report_id)
    allowed = {"name", "description", "question", "sql_generated", "status"}
    sets = []
    params: list = []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            params.append(v)
    if "datamart_ids" in fields:
        sets.append("datamart_ids = ?")
        params.append(json.dumps(fields["datamart_ids"] or []))
    if "diamond_layer_ids" in fields:
        sets.append("diamond_layer_ids = ?")
        params.append(json.dumps(fields["diamond_layer_ids"] or []))
    if "definition" in fields:
        sets.append("definition = ?")
        params.append(json.dumps(fields["definition"] or {}))
    if not sets:
        return get_report(report_id)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    sets.append("version = version + 1")
    params.append(report_id)
    conn = get_sync_connection()
    try:
        conn.execute(f"UPDATE reports SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return get_report(report_id)
    finally:
        conn.close()


def get_report(report_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM reports WHERE id = ?", (report_id,)).fetchone()
        return _row_to_report(row) if row else None
    finally:
        conn.close()


def list_reports(owner_id: int, include_published: bool = True) -> list[dict]:
    """Lista reports do owner (qualquer status) e, se include_published, também
    publicados de outros donos. Filtragem fina por datamart fica na rota.
    """
    conn = get_sync_connection()
    try:
        if include_published:
            sql = (
                "SELECT r.*, u.login AS owner_login, u.display_name AS owner_display_name "
                "FROM reports r JOIN users u ON u.id = r.owner_id "
                "WHERE r.owner_id = ? OR r.status = 'published' "
                "ORDER BY r.updated_at DESC"
            )
            params = (owner_id,)
        else:
            sql = (
                "SELECT r.*, u.login AS owner_login, u.display_name AS owner_display_name "
                "FROM reports r JOIN users u ON u.id = r.owner_id "
                "WHERE r.owner_id = ? ORDER BY r.updated_at DESC"
            )
            params = (owner_id,)
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_report(r) for r in rows]
    finally:
        conn.close()


def list_published_reports() -> list[dict]:
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT r.*, u.login AS owner_login, u.display_name AS owner_display_name "
            "FROM reports r JOIN users u ON u.id = r.owner_id "
            "WHERE r.status = 'published' ORDER BY r.updated_at DESC"
        ).fetchall()
        return [_row_to_report(r) for r in rows]
    finally:
        conn.close()


def delete_report(report_id: int, owner_id: int | None = None) -> bool:
    """Apaga um report. Se *owner_id* é fornecido, exige que coincida (não-admin)."""
    conn = get_sync_connection()
    try:
        if owner_id is not None:
            cur = conn.execute(
                "DELETE FROM reports WHERE id = ? AND owner_id = ?",
                (report_id, owner_id),
            )
        else:
            cur = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Análise Executiva — decks salvos (P2: Deck vivo)
# ---------------------------------------------------------------------------

def _row_to_exec_deck(row, include_spec: bool = True) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("datamart_ids", "diamond_layer_ids"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    if include_spec:
        try:
            d["deck_spec"] = json.loads(d.get("deck_spec") or "{}")
        except Exception:
            d["deck_spec"] = {}
    else:
        d.pop("deck_spec", None)
    return d


def create_exec_deck(owner_id: int, name: str, question: str,
                     datamart_ids: list[int] | None,
                     diamond_layer_ids: list[int] | None,
                     deck_spec: dict | None) -> dict:
    n_slides = len((deck_spec or {}).get("slides") or [])
    conn = get_sync_connection()
    try:
        did = _exec_returning_id(
            conn,
            "INSERT INTO exec_decks (owner_id, name, question, datamart_ids, "
            "diamond_layer_ids, deck_spec, n_slides) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (owner_id, name, question or "", json.dumps(datamart_ids or []),
             json.dumps(diamond_layer_ids or []), json.dumps(deck_spec or {}), n_slides),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM exec_decks WHERE id = ?", (did,)).fetchone()
        return _row_to_exec_deck(row)
    finally:
        conn.close()


def get_exec_deck(deck_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM exec_decks WHERE id = ?", (deck_id,)).fetchone()
        return _row_to_exec_deck(row) if row else None
    finally:
        conn.close()


def list_exec_decks(owner_id: int) -> list[dict]:
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT id, owner_id, name, question, datamart_ids, diamond_layer_ids, "
            "n_slides, created_at, updated_at FROM exec_decks "
            "WHERE owner_id = ? ORDER BY updated_at DESC",
            (owner_id,),
        ).fetchall()
        return [_row_to_exec_deck(r, include_spec=False) for r in rows]
    finally:
        conn.close()


def update_exec_deck(deck_id: int, deck_spec: dict | None = None,
                     name: str | None = None) -> dict | None:
    sets: list[str] = []
    params: list = []
    if name is not None:
        sets.append("name = ?"); params.append(name)
    if deck_spec is not None:
        sets.append("deck_spec = ?"); params.append(json.dumps(deck_spec or {}))
        sets.append("n_slides = ?"); params.append(len((deck_spec or {}).get("slides") or []))
    if not sets:
        return get_exec_deck(deck_id)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(deck_id)
    conn = get_sync_connection()
    try:
        conn.execute(f"UPDATE exec_decks SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return get_exec_deck(deck_id)
    finally:
        conn.close()


def delete_exec_deck(deck_id: int, owner_id: int | None = None) -> bool:
    conn = get_sync_connection()
    try:
        if owner_id is not None:
            cur = conn.execute("DELETE FROM exec_decks WHERE id = ? AND owner_id = ?", (deck_id, owner_id))
        else:
            cur = conn.execute("DELETE FROM exec_decks WHERE id = ?", (deck_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Playbooks — jogadas curadas (coleções de perguntas) para a Análise Executiva
# ---------------------------------------------------------------------------

# Sementes do sistema: as perguntas que antes ficavam fixas no template, agora
# agrupadas em jogadas temáticas e compartilhadas com toda a organização.
_SYSTEM_PLAYBOOK_SEEDS: list[dict] = [
    {
        "title": "Captura de Banda Larga — Diagnóstico 60 dias",
        "category": "Captura",
        "emoji": "📡",
        "description": "Por que a captura está baixa e como reagir no curto prazo.",
        "questions": [
            "Por que a captura de Banda Larga está baixa e o que fazer em 60 dias?",
            "Como evoluiu a captura de BL por tempo de base (cohort 0–90 dias)?",
        ],
    },
    {
        "title": "Alocação de Orçamento & Canais",
        "category": "Conversão",
        "emoji": "💸",
        "description": "Onde investir para converter mais — causa, não correlação.",
        "questions": [
            "Quais canais convertem melhor e onde realocar o orçamento?",
            "Qual o efeito do App na conversão (causa, não correlação)?",
        ],
    },
    {
        "title": "Risco de Churn de Recarga",
        "category": "Retenção",
        "emoji": "🔻",
        "description": "Quem está prestes a sair e quanto está em jogo.",
        "questions": [
            "Quem está em maior risco de churn de recarga e qual o valor em risco?",
        ],
    },
    {
        "title": "ARPU & Cross-sell",
        "category": "Receita",
        "emoji": "💰",
        "description": "Decompor receita e achar a próxima oferta certa.",
        "questions": [
            "Como decompor o ARPU por faixa de recarga e canal?",
            "Onde está a maior oportunidade de cross-sell na base?",
        ],
    },
]


def _row_to_playbook(row, include_questions: bool = True) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("questions", "datamart_ids", "diamond_layer_ids"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    if not include_questions:
        d.pop("questions", None)
    return d


def ensure_system_playbooks() -> None:
    """Idempotente: semeia as jogadas curadas do sistema na primeira vez que
    houver um usuário dono disponível. As tabelas internas são criadas no boot,
    mas o usuário root só nasce no 1º login — por isso a semente é preguiçosa,
    disparada a partir das rotas de listagem."""
    conn = get_sync_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) AS n FROM playbooks WHERE is_system = 1")
        n = cur.fetchone()
        if (n["n"] if isinstance(n, dict) else n[0]) > 0:
            return
        owner = conn.execute(
            "SELECT id FROM users "
            "ORDER BY (user_type = 'root') DESC, (user_type IN ('superuser','admin')) DESC, id ASC "
            "LIMIT 1"
        ).fetchone()
        if owner is None:
            return  # nenhum usuário ainda; tenta de novo na próxima listagem
        owner_id = owner["id"] if isinstance(owner, dict) else owner[0]
        for seed in _SYSTEM_PLAYBOOK_SEEDS:
            conn.execute(
                "INSERT INTO playbooks (owner_id, title, category, description, emoji, "
                "questions, datamart_ids, diamond_layer_ids, visibility, is_system, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, '[]', '[]', 'shared', 1, 'Sistema')",
                (owner_id, seed["title"], seed["category"], seed["description"],
                 seed["emoji"], json.dumps(seed["questions"])),
            )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def create_playbook(owner_id: int, title: str, category: str = "",
                    description: str = "", emoji: str = "📊",
                    questions: list[str] | None = None,
                    datamart_ids: list[int] | None = None,
                    diamond_layer_ids: list[int] | None = None,
                    visibility: str = "private", created_by: str = "",
                    is_system: int = 0) -> dict:
    conn = get_sync_connection()
    try:
        pid = _exec_returning_id(
            conn,
            "INSERT INTO playbooks (owner_id, title, category, description, emoji, "
            "questions, datamart_ids, diamond_layer_ids, visibility, is_system, created_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (owner_id, title, category or "", description or "", emoji or "📊",
             json.dumps(questions or []), json.dumps(datamart_ids or []),
             json.dumps(diamond_layer_ids or []),
             visibility if visibility in ("private", "shared") else "private",
             1 if is_system else 0, created_by or ""),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM playbooks WHERE id = ?", (pid,)).fetchone()
        return _row_to_playbook(row)
    finally:
        conn.close()


def get_playbook(playbook_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM playbooks WHERE id = ?", (playbook_id,)).fetchone()
        return _row_to_playbook(row) if row else None
    finally:
        conn.close()


def list_playbooks_for_user(user_id: int) -> list[dict]:
    """Os playbooks do usuário + todos os compartilhados (org). Alimenta os
    chips da Análise Executiva e a visão padrão do modal Biblioteca."""
    ensure_system_playbooks()
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM playbooks WHERE owner_id = ? OR visibility = 'shared' "
            "ORDER BY is_system DESC, updated_at DESC",
            (user_id,),
        ).fetchall()
        return [_row_to_playbook(r) for r in rows]
    finally:
        conn.close()


def list_all_playbooks() -> list[dict]:
    """Visão admin: todos os playbooks, com login/nome do dono para curadoria."""
    ensure_system_playbooks()
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT p.*, u.login AS owner_login, u.display_name AS owner_name "
            "FROM playbooks p JOIN users u ON p.owner_id = u.id "
            "ORDER BY p.is_system DESC, p.updated_at DESC"
        ).fetchall()
        return [_row_to_playbook(r) for r in rows]
    finally:
        conn.close()


def update_playbook(playbook_id: int, title: str | None = None,
                    category: str | None = None, description: str | None = None,
                    emoji: str | None = None, questions: list[str] | None = None,
                    datamart_ids: list[int] | None = None,
                    diamond_layer_ids: list[int] | None = None,
                    visibility: str | None = None) -> dict | None:
    sets: list[str] = []
    params: list = []
    if title is not None:
        sets.append("title = ?"); params.append(title)
    if category is not None:
        sets.append("category = ?"); params.append(category)
    if description is not None:
        sets.append("description = ?"); params.append(description)
    if emoji is not None:
        sets.append("emoji = ?"); params.append(emoji)
    if questions is not None:
        sets.append("questions = ?"); params.append(json.dumps(questions))
    if datamart_ids is not None:
        sets.append("datamart_ids = ?"); params.append(json.dumps(datamart_ids))
    if diamond_layer_ids is not None:
        sets.append("diamond_layer_ids = ?"); params.append(json.dumps(diamond_layer_ids))
    if visibility is not None and visibility in ("private", "shared"):
        sets.append("visibility = ?"); params.append(visibility)
    if not sets:
        return get_playbook(playbook_id)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    params.append(playbook_id)
    conn = get_sync_connection()
    try:
        conn.execute(f"UPDATE playbooks SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return get_playbook(playbook_id)
    finally:
        conn.close()


def delete_playbook(playbook_id: int, owner_id: int | None = None) -> bool:
    conn = get_sync_connection()
    try:
        if owner_id is not None:
            cur = conn.execute("DELETE FROM playbooks WHERE id = ? AND owner_id = ?", (playbook_id, owner_id))
        else:
            cur = conn.execute("DELETE FROM playbooks WHERE id = ?", (playbook_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Failures — registro de falhas para troubleshooting (Configurações › Falhas)
# ---------------------------------------------------------------------------

# Colunas pesadas omitidas na listagem para manter a grade leve.
_FAILURE_HEAVY_COLS = ("traceback", "snapshot_html", "screenshot")
_FAILURE_LIST_COLS = (
    "id, user_id, user_login, user_name, source, question, sql_generated, "
    "error_message, error_type, model, analysis_type_id, datamart_ids, "
    "diamond_layer_ids, auto_corrected, corrected_sql, duration_ms, status, created_at"
)


def _row_to_failure(row, include_heavy: bool = True) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in ("datamart_ids", "diamond_layer_ids"):
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    if not include_heavy:
        for k in _FAILURE_HEAVY_COLS:
            d.pop(k, None)
    return d


def create_failure(user_id: int | None = None, user_login: str = "", user_name: str = "",
                   source: str = "query", question: str = "", sql_generated: str = "",
                   error_message: str = "", error_type: str = "", traceback: str = "",
                   response_text: str = "", snapshot_html: str = "", screenshot: str = "",
                   model: str = "", analysis_type_id: int | None = None,
                   datamart_ids: list[int] | None = None,
                   diamond_layer_ids: list[int] | None = None,
                   auto_corrected: int = 0, corrected_sql: str = "",
                   duration_ms: int = 0, status: str = "open") -> int:
    """Grava uma falha. Retorna o id (para anexar print/snapshot depois).

    ``status`` permite gravar falhas auto-corrigidas já como 'resolved', para
    não poluir a lista de falhas abertas (a falha continua registrada/auditável)."""
    st = status if status in ("open", "resolved") else "open"
    conn = get_sync_connection()
    try:
        fid = _exec_returning_id(
            conn,
            "INSERT INTO failures (user_id, user_login, user_name, source, question, "
            "sql_generated, error_message, error_type, traceback, response_text, "
            "snapshot_html, screenshot, model, analysis_type_id, datamart_ids, "
            "diamond_layer_ids, auto_corrected, corrected_sql, duration_ms, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, user_login or "", user_name or "", source or "query", question or "",
             sql_generated or "", error_message or "", error_type or "", traceback or "",
             response_text or "", snapshot_html or "", screenshot or "", model or "",
             analysis_type_id, json.dumps(datamart_ids or []), json.dumps(diamond_layer_ids or []),
             1 if auto_corrected else 0, corrected_sql or "", int(duration_ms or 0), st),
        )
        conn.commit()
        return fid
    finally:
        conn.close()


def get_failure(failure_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM failures WHERE id = ?", (failure_id,)).fetchone()
        return _row_to_failure(row) if row else None
    finally:
        conn.close()


def list_failures(limit: int = 300, status: str | None = None) -> list[dict]:
    """Lista falhas (sem colunas pesadas), mais recentes primeiro."""
    conn = get_sync_connection()
    try:
        if status in ("open", "resolved"):
            rows = conn.execute(
                f"SELECT {_FAILURE_LIST_COLS} FROM failures WHERE status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (status, int(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT {_FAILURE_LIST_COLS} FROM failures ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_row_to_failure(r, include_heavy=False) for r in rows]
    finally:
        conn.close()


def update_failure_artifact(failure_id: int, screenshot: str | None = None,
                           snapshot_html: str | None = None) -> bool:
    """Anexa o print (data URL) e/ou o snapshot HTML a uma falha já gravada."""
    sets: list[str] = []
    params: list = []
    if screenshot is not None:
        sets.append("screenshot = ?"); params.append(screenshot)
    if snapshot_html is not None:
        sets.append("snapshot_html = ?"); params.append(snapshot_html)
    if not sets:
        return False
    params.append(failure_id)
    conn = get_sync_connection()
    try:
        cur = conn.execute(f"UPDATE failures SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_failure_status(failure_id: int, status: str) -> bool:
    if status not in ("open", "resolved"):
        return False
    conn = get_sync_connection()
    try:
        cur = conn.execute("UPDATE failures SET status = ? WHERE id = ?", (status, failure_id))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_failure(failure_id: int) -> bool:
    conn = get_sync_connection()
    try:
        cur = conn.execute("DELETE FROM failures WHERE id = ?", (failure_id,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Query history — histórico de consultas por usuário (painel lateral)
# ---------------------------------------------------------------------------

def get_query_history(user_login: str, limit: int = 50) -> list[dict]:
    """Histórico de consultas da tela Consultar, mais recentes primeiro. Esconde
    entradas legadas cuja 'pergunta' é SQL cru (poluição de fluxos internos antigos
    como a Análise Executiva). Fluxos novos nem registram — só a tela Consultar
    grava (run_query log_history). O \\b evita esconder palavras PT (Selecione/Within)."""
    conn = get_sync_connection()
    try:
        # Folga no LIMIT p/ manter ~limit itens após filtrar as legadas SQL.
        rows = conn.execute(
            "SELECT id, question, sql_generated, result_summary, created_at "
            "FROM query_history WHERE user_login = ? ORDER BY created_at DESC LIMIT ?",
            (user_login or "", int(limit) * 2 + 20),
        ).fetchall()
        out = [dict(r) for r in rows
               if not re.match(r"^\s*(select|with)\b", r["question"] or "", re.IGNORECASE)]
        return out[: int(limit)]
    finally:
        conn.close()


def delete_query_history_item(history_id: int, user_login: str) -> bool:
    conn = get_sync_connection()
    try:
        cur = conn.execute(
            "DELETE FROM query_history WHERE id = ? AND user_login = ?",
            (history_id, user_login or ""),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def clear_query_history(user_login: str) -> int:
    conn = get_sync_connection()
    try:
        cur = conn.execute("DELETE FROM query_history WHERE user_login = ?", (user_login or "",))
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
