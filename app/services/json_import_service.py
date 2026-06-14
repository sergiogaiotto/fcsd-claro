"""
Fale com Seus Dados — JSON Import Service

Busca dados de URLs JSON com suporte a:
- Parâmetros de data {date_start} / {date_end}
- Extração por JSONPath (notação ponto)
- Auto-detecção do primeiro array no JSON
- Achatamento (flatten) de objetos aninhados
- Modo append ou replace na tabela SQLite
"""

import json
import re
from datetime import date, datetime
from typing import Optional

import pandas as pd
import requests


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

DATE_FORMATS = {
    "dd/MM/yyyy":  lambda d: d.strftime("%d/%m/%Y"),
    "yyyy-MM-dd":  lambda d: d.strftime("%Y-%m-%d"),
    "dd-MM-yyyy":  lambda d: d.strftime("%d-%m-%Y"),
    "MM/dd/yyyy":  lambda d: d.strftime("%m/%d/%Y"),
    "yyyyMMdd":    lambda d: d.strftime("%Y%m%d"),
    "dd/MM/yy":    lambda d: d.strftime("%d/%m/%y"),
}


def format_date(d: date, fmt: str) -> str:
    fn = DATE_FORMATS.get(fmt)
    return fn(d) if fn else d.strftime("%Y-%m-%d")


def resolve_url(template: str, date_start: str, date_end: str) -> str:
    return (
        template
        .replace("{date_start}", date_start)
        .replace("{date_end}", date_end)
        .replace("{today}", date.today().isoformat())
    )


# ---------------------------------------------------------------------------
# JSON navigation helpers
# ---------------------------------------------------------------------------

def get_by_path(obj, path: str):
    """Navigate JSON by dot-notation path. e.g. 'chart.result.0.meta'"""
    if not path or path.strip() == "":
        return obj
    parts = path.strip(".").split(".")
    current = obj
    for part in parts:
        if current is None:
            return None
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def find_first_array(obj, depth=0, max_depth=8):
    """Recursively find the first non-empty array of objects in the JSON."""
    if depth > max_depth:
        return None, None
    if isinstance(obj, list):
        if len(obj) > 0:
            return obj, ""
        return None, None
    if isinstance(obj, dict):
        for key, val in obj.items():
            result, sub_path = find_first_array(val, depth + 1, max_depth)
            if result is not None:
                path = key if not sub_path else f"{key}.{sub_path}"
                return result, path
    return None, None


# ---------------------------------------------------------------------------
# Flattening
# ---------------------------------------------------------------------------

def flatten_row(row, parent_key="", sep="_", max_depth=4, _depth=0):
    """Flatten a nested dict into a flat dict with underscore-separated keys."""
    if _depth > max_depth:
        return {parent_key: json.dumps(row, ensure_ascii=False)} if parent_key else {}
    items = {}
    if isinstance(row, dict):
        for k, v in row.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else str(k)
            if isinstance(v, dict) and v:
                items.update(flatten_row(v, new_key, sep, max_depth, _depth + 1))
            elif isinstance(v, list):
                if v and isinstance(v[0], (int, float, str, bool)):
                    items[new_key] = json.dumps(v)
                elif v and isinstance(v[0], dict):
                    items.update(flatten_row(v[0], new_key, sep, max_depth, _depth + 1))
                else:
                    items[new_key] = str(v)
            else:
                items[new_key] = v
    else:
        items[parent_key or "value"] = row
    return items


def sanitize_col(name: str) -> str:
    name = re.sub(r"[^\w]", "_", str(name).strip())
    name = re.sub(r"_+", "_", name).strip("_").lower()
    if name and name[0].isdigit():
        name = f"col_{name}"
    return name or "col"


# ---------------------------------------------------------------------------
# Core fetch + import
# ---------------------------------------------------------------------------

def fetch_and_import_json(
    url: str,
    table_name: str,
    json_path: str = "",
    append: bool = False,
    http_headers: dict | None = None,
    datamart_id: int | None = None,
    db_path: str = "",  # kept for API compatibility; ignored (Postgres engine is used)
) -> dict:
    """
    Fetch JSON from URL, extract array, flatten rows, import to PostgreSQL.

    Returns:
        dict with keys: rows_imported, columns, table_name, detected_path
        or: error (str)
    """
    # ── HTTP request ──────────────────────────────────────────────────────
    try:
        resp = requests.get(
            url,
            headers=http_headers or {},
            timeout=30,
            verify=True,
        )
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        return {"error": "Timeout: servidor não respondeu em 30 segundos."}
    except requests.exceptions.SSLError as e:
        return {"error": f"Erro SSL: {str(e)[:120]}"}
    except requests.exceptions.HTTPError as e:
        return {"error": f"HTTP {resp.status_code}: {str(e)[:120]}"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Erro de conexão: {str(e)[:200]}"}

    # ── Parse JSON ────────────────────────────────────────────────────────
    try:
        data = resp.json()
    except (ValueError, json.JSONDecodeError) as e:
        preview = resp.text[:200]
        return {"error": f"Resposta não é JSON válido: {str(e)[:100]}. Preview: {preview}"}

    # ── Extract array ─────────────────────────────────────────────────────
    detected_path = json_path or ""
    if json_path and json_path.strip():
        extracted = get_by_path(data, json_path)
        if extracted is None:
            return {"error": f"Caminho JSON '{json_path}' não encontrado na resposta."}
    else:
        if isinstance(data, list):
            extracted = data
        elif isinstance(data, dict):
            extracted, detected_path = find_first_array(data)
            if extracted is None:
                extracted = [data]
                detected_path = "(raiz)"
        else:
            extracted = [{"value": data}]
            detected_path = "(raiz)"

    # Wrap single object
    if isinstance(extracted, dict):
        extracted = [extracted]

    if not isinstance(extracted, list):
        return {
            "error": (
                f"O caminho não aponta para um array. "
                f"Tipo encontrado: {type(extracted).__name__}. "
                "Especifique o caminho JSON manualmente."
            )
        }

    if not extracted:
        return {"error": "Array JSON está vazio — nenhum dado para importar."}

    # ── Flatten rows ──────────────────────────────────────────────────────
    rows = []
    for item in extracted:
        if isinstance(item, dict):
            rows.append(flatten_row(item))
        else:
            rows.append({"value": item})

    if not rows:
        return {"error": "Nenhuma linha extraída após achatamento do JSON."}

    df = pd.DataFrame(rows)

    # Sanitize column names
    df.columns = [sanitize_col(c) for c in df.columns]

    # Remove fully-null columns
    df = df.dropna(axis=1, how="all")

    # ── Import to PostgreSQL ──────────────────────────────────────────────
    try:
        from app.core.database import engine as _pg_engine, invalidate_tables_cache
        if_exists = "append" if append else "replace"
        df.to_sql(table_name, _pg_engine, if_exists=if_exists, index=False)
        invalidate_tables_cache()
    except Exception as e:
        return {"error": f"Erro ao salvar no banco: {str(e)[:200]}"}

    # ── Assign to DataMart ────────────────────────────────────────────────
    if datamart_id:
        try:
            from app.core.database import assign_table_to_datamart
            assign_table_to_datamart(datamart_id, table_name)
        except Exception:
            pass

    # ── Reset agent ───────────────────────────────────────────────────────
    try:
        from app.services.agent_service import reset_agent
        reset_agent()
    except Exception:
        pass

    return {
        "rows_imported": len(df),
        "columns": list(df.columns),
        "table_name": table_name,
        "detected_path": detected_path,
    }


# ---------------------------------------------------------------------------
# Preview (fetch without saving)
# ---------------------------------------------------------------------------

def preview_json_url(
    url: str,
    json_path: str = "",
    http_headers: dict | None = None,
    max_rows: int = 5,
) -> dict:
    """Fetch and return a preview without writing to DB."""
    try:
        resp = requests.get(url, headers=http_headers or {}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e)[:200]}

    if json_path and json_path.strip():
        extracted = get_by_path(data, json_path)
        detected_path = json_path
    else:
        if isinstance(data, list):
            extracted, detected_path = data, "(raiz)"
        elif isinstance(data, dict):
            extracted, detected_path = find_first_array(data)
            if extracted is None:
                extracted = [data]
                detected_path = "(raiz)"
        else:
            extracted = [{"value": data}]
            detected_path = "(raiz)"

    if isinstance(extracted, dict):
        extracted = [extracted]
    if not isinstance(extracted, list):
        extracted = [{"value": str(extracted)}]

    sample = extracted[:max_rows]
    rows = [flatten_row(r) if isinstance(r, dict) else {"value": r} for r in sample]
    columns = list(pd.DataFrame(rows).columns) if rows else []

    return {
        "total_in_array": len(extracted),
        "columns": [sanitize_col(c) for c in columns],
        "sample": rows,
        "detected_path": detected_path,
        "raw_structure": _describe_structure(data),
    }


def _describe_structure(obj, depth=0, max_depth=4) -> str:
    """Return a compact structural description of a JSON value."""
    if depth > max_depth:
        return "..."
    if isinstance(obj, dict):
        keys = list(obj.keys())[:8]
        inner = ", ".join(f"{k}: {_describe_structure(obj[k], depth+1, max_depth)}" for k in keys)
        suffix = ", ..." if len(obj) > 8 else ""
        return "{" + inner + suffix + "}"
    if isinstance(obj, list):
        n = len(obj)
        if n == 0:
            return "[]"
        sample = _describe_structure(obj[0], depth+1, max_depth)
        return f"[{sample}] ({n} itens)"
    if isinstance(obj, str):
        return f'"{obj[:24]}{"..." if len(obj) > 24 else ""}"'
    return str(obj)
