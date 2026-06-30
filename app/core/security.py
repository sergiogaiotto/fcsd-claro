import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from app.core.config import settings
from app.core.database import get_sync_connection


# ---------------------------------------------------------------------------
# API Key Management (existing)
# ---------------------------------------------------------------------------

def hash_api_key(raw_key: str) -> str:
    salted = f"{settings.api_salt}{raw_key}"
    return hashlib.sha256(salted.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def create_api_key(label: str) -> dict:
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    conn = get_sync_connection()
    try:
        conn.execute(
            "INSERT INTO api_keys (key_hash, label) VALUES (?, ?)",
            (key_hash, label),
        )
        conn.commit()
        return {"key": raw_key, "label": label}
    finally:
        conn.close()


def validate_api_key(raw_key: str) -> bool:
    key_hash = hash_api_key(raw_key)
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            "SELECT key_hash FROM api_keys WHERE key_hash = ? AND is_active = 1",
            (key_hash,),
        )
        row = cursor.fetchone()
        if not row:
            return False
        return hmac.compare_digest(row[0], key_hash)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Password Hashing
# ---------------------------------------------------------------------------

def hash_password(password: str) -> str:
    iterations = 310000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${digest.hex()}"


def _verify_legacy_password(password: str, password_hash: str) -> bool:
    legacy_hash = hashlib.sha256(f"{settings.api_salt}:{password}".encode("utf-8")).hexdigest()
    return hmac.compare_digest(legacy_hash, password_hash)


def verify_password(password: str, password_hash: str) -> bool:
    if password_hash.startswith("pbkdf2_sha256$"):
        try:
            _, iterations, salt_hex, digest_hex = password_hash.split("$", 3)
            derived = hashlib.pbkdf2_hmac(
                "sha256",
                password.encode("utf-8"),
                bytes.fromhex(salt_hex),
                int(iterations),
            )
            return hmac.compare_digest(derived.hex(), digest_hex)
        except Exception:
            return False
    return _verify_legacy_password(password, password_hash)


# ---------------------------------------------------------------------------
# User role helpers
# ---------------------------------------------------------------------------

ADMIN_ROLES = {"root", "superuser", "admin"}
UPLOAD_ROLES = {"root", "superuser", "admin", "analista", "engenheiro_dados"}
CODEGEN_ROLES = {"root", "superuser", "admin", "engenheiro_dados"}
ALL_ROLES = {"root", "superuser", "admin", "analista", "engenheiro_dados", "user"}

def is_analista(user: dict) -> bool:
    return user.get("user_type") == "analista"

def acts_as_analista(user: dict) -> bool:
    """Papéis com o fluxo self-service do analista: upload para o DataMart pessoal
    `dm-{login}` (forçado + auto-atribuído) e drop das próprias tabelas. O
    `engenheiro_dados` herda isso ALÉM dos seus privilégios próprios (codegen,
    catálogo, produtos de dados), que são governados por gates separados."""
    return user.get("user_type") in ("analista", "engenheiro_dados")

def is_engenheiro_dados(user: dict) -> bool:
    return user.get("user_type") == "engenheiro_dados"

def can_upload(user: dict) -> bool:
    return user.get("user_type") in UPLOAD_ROLES

def can_codegen(user: dict) -> bool:
    """Acesso ao módulo TDIA-CodeGen: Root, Admin/Superuser e Engenheiro de Dados."""
    return user.get("user_type") in CODEGEN_ROLES

def is_admin(user: dict) -> bool:
    return user.get("user_type") in ADMIN_ROLES

def is_root(user: dict) -> bool:
    return user.get("user_type") == "root"


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

def get_user_count() -> int:
    conn = get_sync_connection()
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]
    except Exception:
        return 0
    finally:
        conn.close()


def create_user(login: str, password: str, user_type: str = "user",
                display_name: str = "", profile_description: str = "",
                datamart_ids: list[int] | None = None,
                diamond_layer_ids: list[int] | None = None) -> dict:
    from app.core.database import _exec_returning_id
    conn = get_sync_connection()
    try:
        user_id = _exec_returning_id(
            conn,
            """INSERT INTO users (login, password_hash, user_type, display_name, profile_description)
               VALUES (?, ?, ?, ?, ?)""",
            (login, hash_password(password), user_type, display_name, profile_description),
        )
        conn.commit()

        # Assign datamarts
        if datamart_ids:
            for dm_id in datamart_ids:
                conn.execute(
                    "INSERT INTO user_datamarts (user_id, datamart_id) VALUES (?, ?) ON CONFLICT (user_id, datamart_id) DO NOTHING",
                    (user_id, dm_id),
                )
            conn.commit()

        # Assign diamond layers
        if diamond_layer_ids:
            for layer_id in diamond_layer_ids:
                conn.execute(
                    "INSERT INTO user_diamond_layers (user_id, layer_id) VALUES (?, ?) ON CONFLICT (user_id, layer_id) DO NOTHING",
                    (user_id, layer_id),
                )
            conn.commit()

        return {"id": user_id, "login": login, "user_type": user_type, "display_name": display_name}
    finally:
        conn.close()


def authenticate_user(login: str, password: str) -> dict | None:
    """Authenticate and return user dict, or None. Auto-creates root if DB is empty."""
    conn = get_sync_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count == 0:
            # First login ever → create root user
            pw_hash = hash_password(password)
            conn.execute(
                """INSERT INTO users (login, password_hash, user_type, display_name, profile_description)
                   VALUES (?, ?, 'root', 'Root', 'Conta root criada automaticamente no primeiro acesso.')""",
                (login, pw_hash),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM users WHERE LOWER(login) = LOWER(?)", (login,)).fetchone()
            if row:
                user = dict(row)
                # Assign all datamarts to root
                dm_cursor = conn.execute("SELECT id FROM datamarts")
                for dm_row in dm_cursor.fetchall():
                    conn.execute(
                        "INSERT INTO user_datamarts (user_id, datamart_id) VALUES (?, ?) ON CONFLICT (user_id, datamart_id) DO NOTHING",
                        (user["id"], dm_row[0]),
                    )
                conn.commit()
                return user
            return None

        # Normal login
        row = conn.execute("SELECT * FROM users WHERE LOWER(login) = LOWER(?) AND is_active = 1", (login,)).fetchone()
        if row is None:
            return None
        user = dict(row)
        if not verify_password(password, user["password_hash"]):
            return None

        # Transparent upgrade for legacy SHA-256 hashes.
        if not user["password_hash"].startswith("pbkdf2_sha256$"):
            new_hash = hash_password(password)
            conn.execute(
                "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (new_hash, datetime.utcnow().isoformat(), user["id"]),
            )
            conn.commit()
            user["password_hash"] = new_hash
        return user
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ? AND is_active = 1", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_users() -> list[dict]:
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            "SELECT id, login, user_type, display_name, profile_description, is_active, created_at, updated_at "
            "FROM users ORDER BY created_at"
        )
        users = []
        for r in cursor.fetchall():
            u = dict(r)
            # Attach datamart ids
            dm_cursor = conn.execute(
                "SELECT datamart_id FROM user_datamarts WHERE user_id = ?", (u["id"],)
            )
            u["datamart_ids"] = [row[0] for row in dm_cursor.fetchall()]
            # Attach diamond layer ids
            dl_cursor = conn.execute(
                "SELECT layer_id FROM user_diamond_layers WHERE user_id = ?", (u["id"],)
            )
            u["diamond_layer_ids"] = [row[0] for row in dl_cursor.fetchall()]
            users.append(u)
        return users
    finally:
        conn.close()


def update_user(user_id: int, **kwargs) -> bool:
    allowed = {"login", "user_type", "display_name", "profile_description", "is_active"}
    fields = {k: v for k, v in kwargs.items() if k in allowed and v is not None}

    # Handle list-fields separately
    datamart_ids = kwargs.get("datamart_ids")
    diamond_layer_ids = kwargs.get("diamond_layer_ids")

    if not fields and datamart_ids is None and diamond_layer_ids is None:
        return False

    conn = get_sync_connection()
    try:
        if fields:
            fields["updated_at"] = datetime.utcnow().isoformat()
            set_clause = ", ".join(f"{k} = ?" for k in fields)
            conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*fields.values(), user_id))

        if datamart_ids is not None:
            conn.execute("DELETE FROM user_datamarts WHERE user_id = ?", (user_id,))
            for dm_id in datamart_ids:
                conn.execute(
                    "INSERT INTO user_datamarts (user_id, datamart_id) VALUES (?, ?) ON CONFLICT (user_id, datamart_id) DO NOTHING",
                    (user_id, dm_id),
                )

        if diamond_layer_ids is not None:
            conn.execute("DELETE FROM user_diamond_layers WHERE user_id = ?", (user_id,))
            for layer_id in diamond_layer_ids:
                conn.execute(
                    "INSERT INTO user_diamond_layers (user_id, layer_id) VALUES (?, ?) ON CONFLICT (user_id, layer_id) DO NOTHING",
                    (user_id, layer_id),
                )

        conn.commit()
        return True
    finally:
        conn.close()


def change_password(user_id: int, new_password: str) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), datetime.utcnow().isoformat(), user_id),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_user(user_id: int) -> bool:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_datamarts WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM user_diamond_layers WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return True
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

SESSION_DURATION_HOURS = 24


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(48)
    expires = datetime.utcnow() + timedelta(hours=SESSION_DURATION_HOURS)
    conn = get_sync_connection()
    try:
        # Pass datetime objects directly — psycopg adapts them to TIMESTAMP
        # natively. Using strings worked too (auto-cast) but was fragile.
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.utcnow(),))
        conn.execute(
            "INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
            (token, user_id, expires),
        )
        conn.commit()
        return token
    finally:
        conn.close()


def _coerce_datetime(value) -> datetime | None:
    """Accept either a ``datetime`` (psycopg returns native objects for
    TIMESTAMP columns) or an ISO-formatted string (legacy SQLite path).
    Returns None on anything else so callers can safely compare."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def validate_session(token: str) -> dict | None:
    """Return user dict if session is valid, else None."""
    if not token:
        return None
    conn = get_sync_connection()
    try:
        row = conn.execute(
            """SELECT s.user_id, s.expires_at, u.id, u.login, u.user_type, u.display_name, u.profile_description, u.is_active
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.token = ? AND u.is_active = 1""",
            (token,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        expires_at = _coerce_datetime(data.get("expires_at"))
        if expires_at is not None and expires_at < datetime.utcnow():
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None
        return data
    finally:
        conn.close()


def destroy_session(token: str):
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()
