"""Verify database connectivity for whichever backend DATABASE_URL points at.

Run from the repo root:

    python scripts/check_db.py

Output:
  - Effective DATABASE_URL (with the password masked)
  - Detected dialect (sqlite / postgres)
  - Server version string
  - Number of tables visible to the connection user
  - Per-table row count for the first 10 tables (cheap sanity check)

Exit code is 0 on success, non-zero on failure. Safe to run repeatedly; it
reads only metadata and does not write anything.
"""

from __future__ import annotations

import sys
from urllib.parse import urlsplit, urlunsplit

# Allow running from repo root without installing the package
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.db_engine import connect, is_postgres, is_sqlite  # noqa: E402


def _mask_url(url: str) -> str:
    """Hide the password component for display."""
    try:
        parts = urlsplit(url)
        if parts.password:
            netloc = parts.netloc.replace(parts.password, "***", 1)
            return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except Exception:
        pass
    return url


def main() -> int:
    print("=" * 64)
    print("Database connectivity check")
    print("=" * 64)
    print(f"DATABASE_URL : {_mask_url(settings.database_url)}")
    print(f"Dialect      : {settings.db_dialect}")
    print()

    try:
        with connect() as conn:
            cur = conn.cursor()
            if is_postgres():
                cur.execute("SELECT version()")
                row = cur.fetchone()
                version = (row.get("version") if isinstance(row, dict) else row[0]) if row else "?"
                print(f"Server       : {version}")

                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                tables = [r["table_name"] if isinstance(r, dict) else r[0] for r in cur.fetchall()]
            elif is_sqlite():
                cur.execute("SELECT sqlite_version()")
                row = cur.fetchone()
                version = row[0] if row else "?"
                print(f"Server       : sqlite {version}")
                cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [r[0] for r in cur.fetchall()]
            else:
                print(f"Unsupported dialect: {settings.db_dialect}")
                return 2

            print(f"Tables found : {len(tables)}")
            if tables:
                print()
                print("First tables (with row counts):")
                for t in tables[:10]:
                    try:
                        cur.execute(f'SELECT COUNT(*) AS n FROM "{t}"')
                        r = cur.fetchone()
                        n = (r["n"] if isinstance(r, dict) else r[0]) if r else 0
                        print(f"  - {t:40s} {n:>10,} rows")
                    except Exception as e:
                        print(f"  - {t:40s} (count failed: {e})")
            print()
            print("OK")
            return 0
    except Exception as e:
        print()
        print("FAILED:", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
