import pandas as pd
import re
from pathlib import Path

from app.core.database import engine, get_sync_connection, invalidate_tables_cache
from app.core.db_engine import DialectConnection, table_exists


def sanitize_table_name(name: str) -> str:
    name = re.sub(r"[^\w]", "_", name.strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if name and name[0].isdigit():
        name = f"t_{name}"
    return name or "unnamed_table"


def _table_exists(conn: DialectConnection, table_name: str) -> bool:
    """Backwards-compatible wrapper around app.core.db_engine.table_exists."""
    return table_exists(conn, table_name)


def import_excel(
    file_path: Path,
    datamart_name: str = "default",
    conflict_strategy: str | None = None,
) -> list[dict]:
    """Import all sheets from an Excel file into PostgreSQL tables.

    Table names are prefixed with the datamart name: ``{datamart}_{sheet}``.
    When ``conflict_strategy`` is ``None`` and any target table already exists,
    those sheets are reported with ``action="conflict"`` and not written.
    Use ``"replace"`` or ``"append"`` to apply a strategy uniformly.
    """
    xls = pd.ExcelFile(file_path, engine="openpyxl")
    report = []
    conn = get_sync_connection()
    dm_part = sanitize_table_name(datamart_name)
    wrote_any = False
    try:
        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name)
            if df.empty:
                report.append({
                    "sheet": sheet_name,
                    "table": None,
                    "action": "skipped",
                    "reason": "Aba vazia",
                    "rows": 0,
                })
                continue

            df.columns = [
                re.sub(r"[^\w]", "_", str(c).strip()).strip("_").lower()
                for c in df.columns
            ]

            sheet_part = sanitize_table_name(sheet_name)
            tbl = f"{dm_part}_{sheet_part}"
            exists = _table_exists(conn, tbl)

            if exists and conflict_strategy not in ("replace", "append"):
                report.append({
                    "sheet": sheet_name,
                    "table": tbl,
                    "action": "conflict",
                    "rows": len(df),
                })
                continue

            if exists:
                if_exists = "replace" if conflict_strategy == "replace" else "append"
                action = "replaced" if conflict_strategy == "replace" else "appended"
            else:
                if_exists = "replace"
                action = "created"

            df.to_sql(tbl, engine, if_exists=if_exists, index=False)
            wrote_any = True

            report.append({
                "sheet": sheet_name,
                "table": tbl,
                "action": action,
                "rows": len(df),
                "columns": list(df.columns),
            })
        if wrote_any:
            invalidate_tables_cache()
        return report
    finally:
        conn.close()


def import_csv(file_path: Path, table_name: str | None = None) -> list[dict]:
    """Import a CSV file into a PostgreSQL table."""
    df = pd.read_csv(file_path, sep=";")
    if df.empty:
        return [{"sheet": file_path.name, "table": None, "action": "skipped", "reason": "CSV vazio", "rows": 0}]

    df.columns = [
        re.sub(r"[^\w]", "_", str(c).strip()).strip("_").lower()
        for c in df.columns
    ]

    tbl = table_name or sanitize_table_name(file_path.stem)
    conn = get_sync_connection()
    try:
        exists = _table_exists(conn, tbl)
        df.to_sql(tbl, engine, if_exists="append" if exists else "replace", index=False)
        action = "appended" if exists else "created"
        invalidate_tables_cache()
        return [{"sheet": file_path.name, "table": tbl, "action": action, "rows": len(df), "columns": list(df.columns)}]
    finally:
        conn.close()
