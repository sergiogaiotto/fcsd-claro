"""
Reportes — banded report engine (Phase 1).

Reuses the existing query pipeline (run_query) so RLS, datamart access and
skill routing all flow naturally. The engine here is purely a presentation
layer: it ingests the rows returned by the agent and organises them into a
banded structure that the frontend renders as HTML.

Phase 1 covers:
- One optional grouping level with header/footer templates
- Per-group aggregations (sum, avg, count, min, max)
- Grand aggregations on the report footer
- Markdown templates with placeholder substitution
- Pre-defined column formatters

Phases 2+ will extend this with horizontal pivot, computed rows and seed
rows. The service is structured so that those additions can plug in without
breaking Phase 1 contracts.
"""

from __future__ import annotations

import re
import datetime as _dt
from typing import Any

from app.services.agent_service import run_query
from app.core.database import get_report


# ---------------------------------------------------------------------------
# Aggregation primitives
# ---------------------------------------------------------------------------

_AGG_FUNCTIONS = {"sum", "avg", "count", "min", "max"}


def _coerce_number(v: Any) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", ".")
        if not s:
            return None
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _aggregate(values: list[Any], fn: str) -> float | int | None:
    nums = [n for n in (_coerce_number(v) for v in values) if n is not None]
    if fn == "count":
        # COUNT considers all non-null values, including non-numeric ones.
        return sum(1 for v in values if v is not None)
    if not nums:
        return None
    if fn == "sum":
        return sum(nums)
    if fn == "avg":
        return sum(nums) / len(nums)
    if fn == "min":
        return min(nums)
    if fn == "max":
        return max(nums)
    return None


# ---------------------------------------------------------------------------
# Formatters (server-side preview values; the frontend gets raw + formatted)
# ---------------------------------------------------------------------------

def _format_value(value: Any, fmt: str) -> str:
    if value is None:
        return ""
    try:
        if fmt == "currency_brl":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            return _br_currency(n)
        if fmt == "number_2":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            return _br_number(n, 2)
        if fmt == "number_0":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            return _br_number(n, 0)
        if fmt == "number_k":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            return _br_number_k(n)
        if fmt == "percent_2":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            return _br_number(n * 100, 2) + "%"
        if fmt == "percent_0":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            return _br_number(n * 100, 0) + "%"
        if fmt == "percent_raw":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            # já em escala 0-100: mantém 2 casas quando não é inteiro (8.40 -> 8,40%)
            return _br_number(n, 0 if float(n).is_integer() else 2) + "%"
        if fmt == "percent_raw_sign":
            n = _coerce_number(value)
            if n is None:
                return str(value)
            sign = "+" if n > 0 else ""
            return sign + _br_number(n, 0 if float(n).is_integer() else 2) + "%"
        if fmt == "date_br":
            return _format_date_br(value)
    except Exception:
        return str(value)
    return str(value)


def _br_number(n: float, decimals: int) -> str:
    s = f"{n:,.{decimals}f}"
    # 1,234,567.89 → 1.234.567,89
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _br_currency(n: float) -> str:
    return "R$ " + _br_number(n, 2)


def _br_number_k(n: float) -> str:
    abs_n = abs(n)
    if abs_n >= 1_000_000_000:
        return _br_number(n / 1_000_000_000, 1) + " B"
    if abs_n >= 1_000_000:
        return _br_number(n / 1_000_000, 1) + " M"
    if abs_n >= 1_000:
        return _br_number(n / 1_000, 1) + " K"
    return _br_number(n, 0)


def _format_date_br(value: Any) -> str:
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, str) and len(value) >= 10:
        try:
            d = _dt.datetime.fromisoformat(value[:19])
            return d.strftime("%d/%m/%Y")
        except Exception:
            return value
    return str(value)


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------

_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


def _resolve_placeholder(path: str, ctx: dict) -> str:
    """Resolves dotted lookups like report.row_count, group.sum_valor.
    Missing keys render as empty string (forgiving in design-time)."""
    cur: Any = ctx
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return ""
    if cur is None:
        return ""
    return str(cur)


def _render_template(tpl: str, ctx: dict) -> str:
    if not tpl:
        return ""
    return _PLACEHOLDER_RE.sub(lambda m: _resolve_placeholder(m.group(1), ctx), tpl)


# ---------------------------------------------------------------------------
# Banded engine
# ---------------------------------------------------------------------------

def _aggregations_to_dict(agg_specs: list[dict], rows: list[dict]) -> dict[str, Any]:
    """Builds a flat lookup keyed by '<fn>_<column>' for placeholders, plus
    a 'list' with display-friendly entries for the renderer."""
    out: dict[str, Any] = {"list": [], "count": len(rows)}
    for spec in agg_specs or []:
        col = spec.get("column", "")
        fn = spec.get("fn", "sum")
        if fn not in _AGG_FUNCTIONS:
            continue
        values = [r.get(col) for r in rows]
        result = _aggregate(values, fn)
        out[f"{fn}_{col}"] = result
        out["list"].append({
            "column": col,
            "fn": fn,
            "label": spec.get("label", "") or f"{fn.upper()}({col})",
            "value": result,
        })
    return out


def _sort_rows(rows: list[dict], group_col: str, sort: str) -> list[dict]:
    if not group_col:
        return rows
    reverse = sort == "desc"
    def keyfn(r):
        v = r.get(group_col)
        # None ordena por último; mistura tipos vira string
        return (v is None, str(v) if v is not None else "")
    return sorted(rows, key=keyfn, reverse=reverse)


def _color_css(raw: Any, rule: str) -> str:
    if not rule:
        return ""
    n = _coerce_number(raw)
    if n is None:
        return ""
    if rule == "negative_red":
        return "rpt-neg" if n < 0 else ""
    if rule == "sign_color":
        if n < 0:
            return "rpt-neg"
        if n > 0:
            return "rpt-pos"
    return ""


def _build_bands(rows: list[dict], definition: dict, ctx_root: dict) -> list[dict]:
    from itertools import groupby

    bands: list[dict] = []
    detail_cols = definition.get("detail_columns") or []
    show_detail = definition.get("show_detail", True)
    group = definition.get("group")
    sub_group = definition.get("sub_group")
    grand_aggs = definition.get("grand_aggregations") or []

    formatted_columns = [{
        "key": c.get("key"),
        "label": c.get("label") or c.get("key"),
        "fmt": c.get("fmt") or "",
        "align": c.get("align") or "",
        "color_rule": c.get("color_rule") or "",
    } for c in detail_cols]

    if show_detail and formatted_columns:
        bands.append({"kind": "detail_header", "columns": formatted_columns})

    def _format_row(r: dict) -> dict:
        cells = []
        for c in formatted_columns:
            raw = r.get(c["key"])
            cells.append({
                "raw": raw,
                "text": _format_value(raw, c["fmt"]),
                "align": c["align"] or _default_align(c["fmt"]),
                "css": _color_css(raw, c["color_rule"]),
            })
        return {"cells": cells}

    def _emit_detail(chunk: list[dict]):
        if show_detail and formatted_columns:
            bands.append({"kind": "detail_rows", "rows": [_format_row(r) for r in chunk]})

    def _emit_sub_groups(chunk: list[dict], parent_ctx: dict):
        if not sub_group or not sub_group.get("column"):
            _emit_detail(chunk)
            return
        sg_col = sub_group["column"]
        sg_sort = sub_group.get("sort", "asc")
        ordered = _sort_rows(chunk, sg_col, sg_sort)
        for sg_val, sg_iter in groupby(ordered, key=lambda r: r.get(sg_col)):
            sg_chunk = list(sg_iter)
            sg_agg = _aggregations_to_dict(sub_group.get("aggregations") or [], sg_chunk)
            sg_agg["value"] = sg_val
            sg_ctx = dict(parent_ctx)
            sg_ctx["sub_group"] = sg_agg
            sg_header = _render_template(sub_group.get("header_template", ""), sg_ctx)
            sg_footer = _render_template(sub_group.get("footer_template", ""), sg_ctx)
            bands.append({
                "kind": "sub_group_header",
                "value": "" if sg_val is None else str(sg_val),
                "html": sg_header or _default_sub_group_header(sg_val),
                "count": len(sg_chunk),
            })
            _emit_detail(sg_chunk)
            bands.append({
                "kind": "sub_group_footer",
                "html": sg_footer,
                "aggregations": [
                    {**a, "text": _format_value(a["value"], _agg_format_hint(sub_group.get("aggregations") or [], a))}
                    for a in sg_agg["list"]
                ],
            })

    if group and group.get("column"):
        col = group["column"]
        ordered = _sort_rows(rows, col, group.get("sort", "asc"))
        for value, group_iter in groupby(ordered, key=lambda r: r.get(col)):
            chunk = list(group_iter)
            agg_ctx = _aggregations_to_dict(group.get("aggregations") or [], chunk)
            agg_ctx["value"] = value
            local_ctx = dict(ctx_root)
            local_ctx["group"] = agg_ctx
            header_html = _render_template(group.get("header_template", ""), local_ctx)
            footer_html = _render_template(group.get("footer_template", ""), local_ctx)
            bands.append({
                "kind": "group_header",
                "value": "" if value is None else str(value),
                "html": header_html or _default_group_header(value),
                "count": len(chunk),
            })
            _emit_sub_groups(chunk, local_ctx)
            bands.append({
                "kind": "group_footer",
                "html": footer_html,
                "aggregations": [
                    {**a, "text": _format_value(a["value"], _agg_format_hint(group.get("aggregations") or [], a))}
                    for a in agg_ctx["list"]
                ],
            })
    else:
        if sub_group and sub_group.get("column"):
            _emit_sub_groups(rows, ctx_root)
        else:
            _emit_detail(rows)

    grand_ctx = _aggregations_to_dict(grand_aggs, rows)
    if grand_ctx["list"]:
        bands.append({
            "kind": "grand_footer",
            "aggregations": [
                {**a, "text": _format_value(a["value"], _agg_format_hint(grand_aggs, a))}
                for a in grand_ctx["list"]
            ],
        })
    return bands, grand_ctx


def _default_group_header(value: Any) -> str:
    return f"<strong>{'' if value is None else value}</strong>"


def _default_sub_group_header(value: Any) -> str:
    return f"<em>{'' if value is None else value}</em>"


def _default_align(fmt: str) -> str:
    if fmt in {"currency_brl", "number_2", "number_0", "number_k",
               "percent_2", "percent_0", "percent_raw", "percent_raw_sign"}:
        return "right"
    if fmt == "date_br":
        return "center"
    return "left"


def _agg_format_hint(spec_list: list[dict], agg: dict) -> str:
    """Tries to use the source column's fmt for the aggregation display."""
    # Without column-level fmt info here we keep number_2 as a sensible default.
    # Caller can override later if column fmt is currency_brl.
    if agg.get("fn") == "count":
        return "number_0"
    return "number_2"


# ---------------------------------------------------------------------------
# Public entrypoints
# ---------------------------------------------------------------------------

async def execute_report_view(
    report_id: int,
    user: dict,
    accessible_tables: list[str] | None = None,
    apply_login_filter: bool = True,
) -> dict:
    rep = get_report(report_id)
    if not rep:
        raise ValueError("Report não encontrado")
    return await render_report(rep, user, accessible_tables, apply_login_filter)


async def render_report(
    rep: dict,
    user: dict,
    accessible_tables: list[str] | None = None,
    apply_login_filter: bool = True,
    segment_filters: list | None = None,
) -> dict:
    """Executes the report's query and returns a fully-rendered band structure.

    Published reports use the saved SQL fast-path; drafts re-run the question
    through the agent so the designer reflects schema changes.

    *segment_filters* (do pré-voo) escopam o SQL no servidor quando possível
    (relatório publicado + SELECT simples) — reduz o volume lido. Se não der p/
    injetar com segurança, roda como antes (o front filtra client-side)."""
    saved_sql = rep.get("sql_generated") if rep.get("status") == "published" else None
    user_login = user.get("login", "") if user else ""
    if saved_sql and segment_filters:
        try:
            from app.services.exec_replay_service import apply_segment_filters_to_sql
            new_sql, applied = apply_segment_filters_to_sql(
                saved_sql, segment_filters, accessible_tables=accessible_tables,
                login=user_login, apply_login_filter=apply_login_filter)
            if applied:
                saved_sql = new_sql
        except Exception:
            pass  # fallback: roda o SQL salvo inteiro (filtro client-side cobre)
    result = await run_query(
        question=rep.get("question") or rep.get("name", ""),
        analysis_type_id=None,
        result_limit=0,  # reports want everything
        user_login=user_login,
        accessible_tables=accessible_tables,
        saved_sql=saved_sql,
        apply_login_filter=apply_login_filter,
    )
    data = result.get("data") or {}
    if "error" in data:
        return {
            "report": _public_report_view(rep),
            "executed_at": _dt.datetime.utcnow().isoformat() + "Z",
            "error": data.get("error"),
            "attempted_sql": data.get("attempted_sql") or result.get("sql_generated", ""),
            "bands": [],
            "row_count": 0,
        }
    columns = data.get("columns") or []
    raw_rows = data.get("rows") or []
    rows = [dict(zip(columns, r)) for r in raw_rows] if raw_rows and isinstance(raw_rows[0], (list, tuple)) else list(raw_rows)
    definition = rep.get("definition") or {}

    ctx_root = {
        "report": {
            "name": rep.get("name", ""),
            "description": rep.get("description", ""),
            "row_count": len(rows),
        },
        "user": {
            "login": user_login,
            "display_name": (user or {}).get("display_name", "") or user_login,
        },
        "date": _dt.date.today().strftime("%d/%m/%Y"),
        "datetime": _dt.datetime.now().strftime("%d/%m/%Y %H:%M"),
    }

    bands, grand_ctx = _build_bands(rows, definition, ctx_root)
    # Expose grand aggregations as report.<fn>_<col> for footer template.
    flat_grand = {k: v for k, v in grand_ctx.items() if k not in ("list", "count")}
    ctx_root["report"].update(flat_grand)

    rendered_report_header = _render_template(definition.get("report_header", ""), ctx_root)
    rendered_report_footer = _render_template(definition.get("report_footer", ""), ctx_root)

    return {
        "report": _public_report_view(rep),
        "executed_at": _dt.datetime.utcnow().isoformat() + "Z",
        "row_count": len(rows),
        "available_columns": list(columns),
        "sql_generated": result.get("sql_generated", ""),
        "report_header_html": rendered_report_header,
        "report_footer_html": rendered_report_footer,
        "page_header": definition.get("page_header", ""),
        "page_footer": definition.get("page_footer", ""),
        "bands": bands,
        "grand_aggregations": grand_ctx.get("list", []),
        "ctx": ctx_root,
    }


def _public_report_view(rep: dict) -> dict:
    """Slim, JSON-safe representation of a report for embedding in responses."""
    return {
        "id": rep.get("id"),
        "name": rep.get("name"),
        "description": rep.get("description"),
        "status": rep.get("status"),
        "owner_id": rep.get("owner_id"),
        "version": rep.get("version"),
        "datamart_ids": rep.get("datamart_ids") or [],
    }
