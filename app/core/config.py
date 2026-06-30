import os
from pathlib import Path
from urllib.parse import quote
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _sanitize_env(value: str) -> str:
    """Strip whitespace and a single pair of surrounding quotes (Render's
    dashboard sometimes preserves quotes literally when copy-pasted)."""
    if value is None:
        return ""
    v = value.strip().lstrip("﻿")  # also strip a stray BOM
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    return v


def _compose_from_db_parts() -> str | None:
    """Compose a Postgres URL from DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_PORT
    if all required pieces are set. Returns None when the trio is missing.

    Each value is sanitized (whitespace + surrounding quotes stripped) and
    every URL-significant character in user/password is percent-encoded so
    the assembled URL parses cleanly.
    """
    host = _sanitize_env(os.getenv("DB_HOST", ""))
    name = _sanitize_env(os.getenv("DB_NAME", ""))
    user = _sanitize_env(os.getenv("DB_USER", ""))
    pwd = _sanitize_env(os.getenv("DB_PASSWORD", ""))
    port = _sanitize_env(os.getenv("DB_PORT", "5432")) or "5432"
    if not (host and name and user):
        return None
    return f"postgresql+psycopg://{quote(user, safe='')}:{quote(pwd, safe='')}@{host}:{port}/{name}"


def _try_sqlalchemy_parse(url: str) -> tuple[bool, str]:
    """Use SQLAlchemy's own URL parser to validate. Returns (ok, error_msg).
    Imports SQLAlchemy lazily so config can still load without it during
    very-early bootstrap or unit tests that mock it out."""
    try:
        from sqlalchemy.engine.url import make_url
        make_url(url)
        return True, ""
    except Exception as e:
        return False, str(e)[:200]


def _mask_url(url: str) -> str:
    """Mask the password component for safe logging."""
    try:
        if "://" not in url:
            return url
        scheme, rest = url.split("://", 1)
        if "@" not in rest:
            return url
        userinfo, hostpart = rest.rsplit("@", 1)
        if ":" in userinfo:
            user, _ = userinfo.split(":", 1)
            return f"{scheme}://{user}:***@{hostpart}"
        return url
    except Exception:
        return "(unparseable)"


def _force_psycopg3_driver(url: str) -> str:
    """Força o driver psycopg 3 (``postgresql+psycopg://``) em QUALQUER URL Postgres.

    O app inteiro usa psycopg 3 e o engine SQLAlchemy passa
    ``connect_args={'prepare_threshold': 3}`` — parâmetro que SÓ o psycopg 3 aceita.
    Mas o SQLAlchemy faz *default* para o dialeto **psycopg2** quando a URL vem como
    ``postgresql://`` / ``postgres://`` (formato típico de Postgres gerenciado/cloud
    e de quem seta DATABASE_URL na mão). Nesse caso o psycopg2 ou não está instalado
    (``ModuleNotFoundError: No module named 'psycopg2'``) ou rejeita
    ``prepare_threshold`` como opção inválida — e a conexão (logo, o upload) quebra.
    Normalizar para ``+psycopg`` elimina os dois casos e ainda resolve o
    ``postgres://`` legado (estilo Heroku/Render) que o SQLAlchemy 2 nem aceita.
    """
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if scheme.split("+", 1)[0].lower() in ("postgresql", "postgres"):
        return "postgresql+psycopg://" + rest
    return url


def _resolve_database_url() -> str:
    """Build the effective PostgreSQL connection URL.

    Resolution order:
      1. Explicit ``DATABASE_URL`` env var when it is a Postgres URL AND
         passes SQLAlchemy's own URL parser.
      2. Fallback to composing from DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_PORT
         (URL-encodes everything safely). This also kicks in when an explicit
         DATABASE_URL is set but unparseable — most often because of an
         unencoded special character in the password, surrounding quotes,
         stray whitespace, or a stray BOM.
      3. Raise ``RuntimeError`` with a clear message — SQLite is no longer
         supported and the app refuses to boot without Postgres credentials.
    """
    import sys

    explicit_raw = os.getenv("DATABASE_URL", "")
    explicit = _sanitize_env(explicit_raw)

    if explicit:
        if not explicit.lower().startswith(("postgresql://", "postgres://", "postgresql+")):
            raise RuntimeError(
                f"DATABASE_URL must be a PostgreSQL URL (got: {explicit[:30]}...). "
                "SQLite is no longer supported."
            )
        # Normaliza para o driver psycopg 3 ANTES de validar/retornar: sem isto, um
        # DATABASE_URL "postgresql://" cru cai no dialeto psycopg2 e o
        # connect_args['prepare_threshold'] do engine quebra a conexão (e o upload).
        explicit = _force_psycopg3_driver(explicit)
        ok, err = _try_sqlalchemy_parse(explicit)
        if ok:
            return explicit
        # Explicit URL won't parse. Try the DB_* fallback.
        composed = _compose_from_db_parts()
        if composed:
            ok2, err2 = _try_sqlalchemy_parse(composed)
            if ok2:
                print(
                    f"WARNING: DATABASE_URL is unparseable ({err}). "
                    "Falling back to the DB_HOST/DB_NAME/DB_USER/DB_PASSWORD "
                    f"composition: {_mask_url(composed)}",
                    file=sys.stderr,
                )
                return composed
            raise RuntimeError(
                f"Both DATABASE_URL ({err}) and the DB_* composition "
                f"({err2}) failed to parse. Composed URL was: "
                f"{_mask_url(composed)}. Verify the values for typos / "
                "stray quotes / whitespace."
            )
        raise RuntimeError(
            f"DATABASE_URL is unparseable: {err}. URL preview "
            f"(password masked): {_mask_url(explicit)}. Either fix the URL "
            "(URL-encode special chars in the password) or set "
            "DB_HOST/DB_NAME/DB_USER/DB_PASSWORD env vars and unset "
            "DATABASE_URL so the app composes a safe URL."
        )

    composed = _compose_from_db_parts()
    if composed:
        ok, err = _try_sqlalchemy_parse(composed)
        if ok:
            return composed
        raise RuntimeError(
            f"DB_* composed URL failed to parse: {err}. Composed URL "
            f"(password masked): {_mask_url(composed)}. Check DB_HOST, "
            "DB_PORT, DB_NAME, DB_USER for typos or stray quotes."
        )

    raise RuntimeError(
        "PostgreSQL is not configured. Set DATABASE_URL or all of "
        "DB_HOST/DB_NAME/DB_USER/DB_PASSWORD/DB_PORT in the environment."
    )

class Settings(BaseSettings):
    # LLM routing: OSS 120B primary, Azure GPT-4o fallback.
    llm_provider: str = os.getenv("LLM_PROVIDER", "oss120b_http")
    llm_sql_provider: str = os.getenv("LLM_SQL_PROVIDER", "oss120b")
    llm_general_provider: str = os.getenv("LLM_GENERAL_PROVIDER", "oss120b")
    llm_fallback_provider: str = os.getenv("LLM_FALLBACK_PROVIDER", "azure")

    llm_timeout_seconds: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "300"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "1"))

    # When true, the NL→SQL agent prompt is enriched with Data Catalog business
    # context (column descriptions, semantic types, PII flags, suggested
    # joins/KPIs) for tables that have a catalog entry. Tables without one fall
    # back to the raw structural schema. Disable to revert to legacy behavior.
    catalog_enrich_agent: bool = os.getenv("CATALOG_ENRICH_AGENT", "true").lower() == "true"

    # OpenAI-compatible OSS endpoint.
    oss120b_url: str = os.getenv(
        "OSS120B_URL",
        "https://hub-gpus.claro.com.br/gpt120/v1/chat/completions",
    ).strip()
    oss120b_model: str = os.getenv("OSS120B_MODEL", "openai/gpt-oss-120b")
    oss120b_api_key: str = os.getenv(
        "OSS120B_API_KEY",
        os.getenv("OSS_API_KEY", "not-needed"),
    )

    # Azure OpenAI fallback.
    azure_openai_api_key: str = os.getenv("AZURE_OPENAI_API_KEY", "")
    azure_openai_endpoint: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    azure_openai_api_version: str = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")
    azure_openai_chat_deployment: str = os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

    # Legacy/OpenAI direct compatibility.
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "")
       
    # OpenAI
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4.1")

    # Database (PostgreSQL only).
    # NOTE: not exposed as a pydantic field. pydantic-settings would
    # otherwise re-load the raw DATABASE_URL env var into this attribute
    # at instantiation, bypassing _resolve_database_url() entirely (the
    # raw value can be malformed — surrounding quotes, unencoded chars,
    # etc. — and that is what we are trying to sanitize). It is set in
    # model_post_init below using the resolver, so any code that does
    # ``settings.database_url`` always sees the cleaned/composed URL.
    # PostgreSQL performance tuning (Docker/managed Postgres).
    # These env vars allow runtime tuning without code changes.
    db_pool_min_size: int = int(os.getenv("DB_POOL_MIN_SIZE", "2"))
    db_pool_max_size: int = int(os.getenv("DB_POOL_MAX_SIZE", "20"))
    db_pool_max_idle_seconds: int = int(os.getenv("DB_POOL_MAX_IDLE_SECONDS", "300"))
    db_pool_timeout_seconds: int = int(os.getenv("DB_POOL_TIMEOUT_SECONDS", "15"))
    db_connect_timeout_seconds: int = int(os.getenv("DB_CONNECT_TIMEOUT_SECONDS", "10"))
    db_statement_timeout_ms: int = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "45000"))
    db_lock_timeout_ms: int = int(os.getenv("DB_LOCK_TIMEOUT_MS", "10000"))
    db_sqlalchemy_pool_size: int = int(os.getenv("DB_SQLALCHEMY_POOL_SIZE", "10"))
    db_sqlalchemy_max_overflow: int = int(os.getenv("DB_SQLALCHEMY_MAX_OVERFLOW", "20"))
    db_sqlalchemy_pool_recycle_seconds: int = int(os.getenv("DB_SQLALCHEMY_POOL_RECYCLE_SECONDS", "1200"))

    # API Security
    api_salt: str = os.getenv("API_SALT", "default-salt")
    api_secret_key: str = os.getenv("API_SECRET_KEY", "default-secret")
    session_secret: str = os.getenv("SESSION_SECRET", "qi-session-secret-change-me")

    # Security
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

    # Langfuse
    langfuse_secret_key: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_public_key: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_host: str = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    # Server
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8000"))

    # Paths
    project_dir: Path = BASE_DIR
    upload_dir: Path = BASE_DIR / "uploads"
    templates_dir: Path = BASE_DIR / "app" / "templates"
    static_dir: Path = BASE_DIR / "app" / "static"
    agents_md: Path = BASE_DIR / "AGENTS.md"
    skills_dir: Path = BASE_DIR / "skills"

    @property
    def oss120b_base_url(self) -> str:
        """Convert full /chat/completions URL into OpenAI-compatible base URL."""
        url = self.oss120b_url.strip()
        if url.endswith("/chat/completions"):
            return url[: -len("/chat/completions")]
        return url.rstrip("/")

    @property
    def database_url(self) -> str:
        """Effective PostgreSQL connection URL.

        Computed at instantiation from _resolve_database_url() and stored
        on the instance under a non-pydantic attribute. We expose it as
        a property so that any access (settings.database_url) returns the
        cleaned/composed URL, not whatever pydantic-settings might try to
        load from the env."""
        return self._database_url

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
# Resolve the database URL AFTER pydantic-settings finishes its env-var
# loading pass. This guarantees our sanitization (strip quotes /
# whitespace, validate via SQLAlchemy, fall back to DB_*) wins over
# whatever pydantic might have parsed from the raw DATABASE_URL.
object.__setattr__(settings, "_database_url", _resolve_database_url())
settings.upload_dir.mkdir(parents=True, exist_ok=True)
