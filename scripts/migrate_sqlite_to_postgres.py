"""One-shot ETL: copy data from a SQLite snapshot into the configured PostgreSQL.

This is meant to run once during the cutover. It:

1. Opens the source SQLite file (default: ``data/quick_insights.db``).
2. Connects to the Postgres database resolved by the app config
   (``DATABASE_URL`` / ``DB_*`` env vars).
3. Ensures the metadata schema exists in Postgres
   (``init_metadata_tables()``).
4. For every table in SQLite (skipping ``sqlite_*`` internals), copies the
   rows into the same-named Postgres table:
     - If the table does not yet exist in Postgres, it is created via
       pandas + SQLAlchemy.
     - If it exists and ``--truncate`` was passed, rows are deleted first
       and copied in bulk.
     - Otherwise rows are appended.

Usage:

    python scripts/migrate_sqlite_to_postgres.py
    python scripts/migrate_sqlite_to_postgres.py --src data/snapshot-2026-05-01.db
    python scripts/migrate_sqlite_to_postgres.py --truncate
    python scripts/migrate_sqlite_to_postgres.py --tables users,sessions,reports

Idempotent against re-runs only when ``--truncate`` is set; otherwise a
second run will append (and likely violate UNIQUE constraints). Always
take a database snapshot before running.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# Repo root on path so app.* imports resolve when running from any cwd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings  # noqa: E402
from app.core.database import init_metadata_tables, engine as pg_engine  # noqa: E402
from app.core.db_engine import connect as pg_connect, table_exists  # noqa: E402


SKIP_PREFIXES = ("sqlite_",)


def list_sqlite_tables(src: Path) -> list[str]:
    conn = sqlite3.connect(str(src))
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        return [r[0] for r in cur.fetchall() if not r[0].startswith(SKIP_PREFIXES)]
    finally:
        conn.close()


def copy_table(src: Path, table: str, truncate: bool) -> tuple[int, str]:
    """Copy one table from SQLite to Postgres. Returns (row_count, action)."""
    sqlite_conn = sqlite3.connect(str(src))
    try:
        df = pd.read_sql_query(f'SELECT * FROM "{table}"', sqlite_conn)
    finally:
        sqlite_conn.close()

    if df.empty:
        return 0, "empty"

    pg_conn = pg_connect()
    try:
        exists = table_exists(pg_conn, table)
    finally:
        pg_conn.close()

    if exists and truncate:
        pg_conn = pg_connect()
        try:
            pg_conn.execute(f'TRUNCATE TABLE "{table}" RESTART IDENTITY CASCADE')
            pg_conn.commit()
        finally:
            pg_conn.close()
        df.to_sql(table, pg_engine, if_exists="append", index=False)
        return len(df), "truncated+inserted"
    if exists:
        df.to_sql(table, pg_engine, if_exists="append", index=False)
        return len(df), "appended"
    df.to_sql(table, pg_engine, if_exists="replace", index=False)
    return len(df), "created+inserted"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--src", type=Path, default=Path("data/quick_insights.db"))
    parser.add_argument("--truncate", action="store_true",
                        help="TRUNCATE existing Postgres tables before copying")
    parser.add_argument("--tables", type=str, default="",
                        help="Comma-separated list of tables to migrate (default: all)")
    parser.add_argument("--init", action="store_true",
                        help="Run init_metadata_tables() against Postgres before copying")
    args = parser.parse_args()

    if not args.src.exists():
        print(f"FAIL: SQLite source not found: {args.src}")
        return 2

    print("=" * 64)
    print("SQLite -> PostgreSQL ETL")
    print("=" * 64)
    print(f"Source     : {args.src}")
    print(f"Target URL : {settings.database_url[:60]}...")
    print(f"Truncate   : {args.truncate}")
    print()

    if args.init:
        print("Initialising Postgres metadata schema...")
        init_metadata_tables()
        print("  ok")
        print()

    all_tables = list_sqlite_tables(args.src)
    if args.tables:
        wanted = {t.strip() for t in args.tables.split(",") if t.strip()}
        all_tables = [t for t in all_tables if t in wanted]
    print(f"Copying {len(all_tables)} table(s):")

    total_rows = 0
    failures = []
    for tbl in all_tables:
        try:
            n, action = copy_table(args.src, tbl, args.truncate)
            total_rows += n
            print(f"  - {tbl:40s} {n:>10,} rows  ({action})")
        except Exception as e:
            failures.append((tbl, str(e)[:120]))
            print(f"  - {tbl:40s} FAIL: {str(e)[:120]}")

    print()
    print(f"Done. {total_rows:,} rows copied across {len(all_tables) - len(failures)} table(s).")
    if failures:
        print(f"{len(failures)} table(s) failed:")
        for t, err in failures:
            print(f"  - {t}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
