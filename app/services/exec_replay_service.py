"""
Análise Executiva — Replay determinístico de deck (recorte + janela).

Reexecuta um deck salvo SEM reinvocar o LLM: reusa o SQL capturado em cada
slide, aplica transforms determinísticos via sqlglot (injeção de filtro de
segmento + troca de janela 3m/6m/12m), reexecuta e recomputa herói/gráfico com
os mesmos helpers da geração. RLS-safe (re-injeta o filtro de login). Degrada
por slide (nunca quebra o deck inteiro).

Pública:
  - analyze_deck_params(deck_spec, accessible_tables) -> dict
  - replay_deck(deck_spec, *, segment_filters, window, user, accessible_tables,
                apply_login_filter) -> dict
"""

from __future__ import annotations

import re as _re
from typing import Any

import sqlglot
from sqlglot import exp

from app.core.database import execute_readonly_sql, get_sync_connection, get_tables_with_login_column
from app.services.exec_analysis_service import (
    _compute_value, _numeric_columns, _normalize_rows, _source_quality,
    _confidence, _json_safe,
)
from app.services.report_service import _format_value, _coerce_number
from app.services.exec_deck_service import _chart_spec, _tables_in_sql

_WINDOWS = ("3m", "6m", "12m")
_WIN_RE = _re.compile(r"^(.*)_(3m|6m|12m)$", _re.IGNORECASE)
_VALID_AGGS = ("first", "sum", "avg", "min", "max", "count")

# Cache simples de colunas por tabela (information_schema) — evita N queries.
_TABLE_COLS_CACHE: dict[str, set[str]] = {}


def _table_columns(table: str) -> set[str]:
    t = (table or "").lower()
    if not t:
        return set()
    if t in _TABLE_COLS_CACHE:
        return _TABLE_COLS_CACHE[t]
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND LOWER(table_name) = ?",
            (t,),
        ).fetchall()
        cols = {str(dict(r)["column_name"]).lower() for r in rows}
        _TABLE_COLS_CACHE[t] = cols
        return cols
    except Exception:
        return set()
    finally:
        conn.close()


def _table_text_columns(table: str) -> list[str]:
    """Colunas categóricas (texto) — candidatas a filtro de segmento."""
    t = (table or "").lower()
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND LOWER(table_name) = ? "
            "ORDER BY ordinal_position",
            (t,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            if str(d.get("data_type", "")).lower() in ("text", "character varying", "varchar", "char", "character"):
                out.append(str(d["column_name"]))
        return out
    except Exception:
        return []
    finally:
        conn.close()


def _distinct_values(table: str, column: str, limit: int = 50) -> list[str]:
    if not _safe_ident(table) or not _safe_ident(column):
        return []
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            f'SELECT DISTINCT "{column}" AS v FROM "{table}" '
            f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {int(limit)}'
        ).fetchall()
        return [str(dict(r)["v"]) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _safe_ident(name: str) -> bool:
    return bool(_re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""))


# ---------------------------------------------------------------------------
# Detecção de colunas temporais (período / intervalo de datas)
# ---------------------------------------------------------------------------

_TEMPORAL_TOKENS = {
    "data", "datas", "date", "datetime", "timestamp", "hora", "ano", "year",
    "mes", "mês", "month", "dia", "day", "periodo", "período", "safra",
    "semestre", "trimestre", "competencia", "competência", "ref",
}


def _name_is_temporal(name: str) -> bool:
    """Heurística de nome (fallback quando não há catálogo). Casa por TOKEN
    (split em não-alfanumérico) para evitar falsos positivos tipo 'media'→'dia'."""
    n = (name or "").lower()
    toks = set(t for t in _re.split(r"[^a-z0-9]+", n) if t)
    if toks & _TEMPORAL_TOKENS:
        return True
    return n.startswith("dt_") or n.startswith("data") or n.endswith("_dt") or "_data_" in n


def _table_typed_columns(table: str) -> dict:
    """{col_lower: (col_name, data_type)} via information_schema."""
    t = (table or "").lower()
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND LOWER(table_name) = ? ORDER BY ordinal_position",
            (t,),
        ).fetchall()
        out = {}
        for r in rows:
            d = dict(r)
            nm = str(d.get("column_name"))
            out[nm.lower()] = (nm, str(d.get("data_type") or ""))
        return out
    except Exception:
        return {}
    finally:
        conn.close()


def _get_column_range(table: str, col: str):
    """(min, max) de uma coluna — pré-preenche o controle início→fim."""
    if not _safe_ident(table) or not _safe_ident(col):
        return None, None
    conn = get_sync_connection()
    try:
        row = conn.execute(
            f'SELECT MIN("{col}") AS mn, MAX("{col}") AS mx FROM "{table}" WHERE "{col}" IS NOT NULL'
        ).fetchone()
        if not row:
            return None, None
        d = dict(row)
        return d.get("mn"), d.get("mx")
    except Exception:
        return None, None
    finally:
        conn.close()


def _temporal_columns_for(tables) -> list[dict]:
    """Colunas temporais das tabelas: por tipo semântico do Catálogo ('data/tempo'),
    por tipo físico (date/timestamp) ou por heurística de nome. Retorna
    [{name, table, kind('date'|'numeric'), min, max}] deduplicado por nome."""
    try:
        from app.services.catalog_service import get_catalog_context
        cat = get_catalog_context([str(t) for t in (tables or [])]) or {}
    except Exception:
        cat = {}
    # mapa case-insensitive nome-tabela -> {col_lower: semantic_type}
    sem_by_table: dict[str, dict] = {}
    for tname, tinfo in (cat or {}).items():
        m = {}
        for c in (tinfo.get("columns") or []):
            m[(c.get("name") or "").lower()] = (c.get("semantic_type") or "").strip().lower()
        sem_by_table[str(tname).lower()] = m

    out: list[dict] = []
    seen: set[str] = set()
    for t in sorted({str(x).lower() for x in (tables or [])}):
        sem = sem_by_table.get(t, {})
        for col_lower, (name, dtype) in _table_typed_columns(t).items():
            if col_lower in seen:
                continue
            dl = (dtype or "").lower()
            is_date_type = ("date" in dl) or ("timestamp" in dl)
            is_temporal = (sem.get(col_lower) == "data/tempo") or is_date_type or _name_is_temporal(name)
            if not is_temporal:
                continue
            kind = "date" if (is_date_type or "time" in dl) else "numeric"
            mn, mx = _get_column_range(t, name)
            seen.add(col_lower)
            out.append({"name": name, "table": t, "kind": kind,
                        "min": _json_safe(mn), "max": _json_safe(mx)})
    return out


# ---------------------------------------------------------------------------
# sqlglot — parse / transforms / regenerate
# ---------------------------------------------------------------------------

def _parse(sql: str):
    try:
        return sqlglot.parse_one(sql, read="postgres")
    except Exception:
        return None


def _slide_tables(node) -> set[str]:
    """Tabelas REAIS referenciadas, excluindo aliases de CTE (evita falso-positivo
    no guard de autorização/RLS quando o SQL usa WITH)."""
    try:
        ctes = {(c.alias or "").lower() for c in node.find_all(exp.CTE)}
        return {(t.name or "").lower() for t in node.find_all(exp.Table)
                if t.name and (t.name or "").lower() not in ctes}
    except Exception:
        return set()


def _valid_columns_for(node) -> set[str]:
    cols: set[str] = set()
    for t in _slide_tables(node):
        cols |= _table_columns(t)
    return cols


def _flatten_and(cond) -> list:
    if isinstance(cond, exp.And):
        return _flatten_and(cond.left) + _flatten_and(cond.right)
    return [cond]


def _pred_on_column(c, column: str) -> bool:
    """Predicado que filtra a coluna — cobre EQ/IN/comparações + BETWEEN, NOT e
    parênteses (desembrulha) para a substituição de mesma-coluna não deixar
    predicados conflitantes."""
    if isinstance(c, (exp.Paren, exp.Not)):
        return _pred_on_column(c.this, column)
    left = c.args.get("this") if isinstance(
        c, (exp.EQ, exp.NEQ, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.In, exp.Like, exp.Is, exp.Between)
    ) else None
    return isinstance(left, exp.Column) and (left.name or "").lower() == (column or "").lower()


def _set_where(node, conditions: list) -> None:
    """Combina condições com AND. Envolve qualquer OR em parênteses para preservar
    a precedência (sem isso, 'a OR b AND filtro' = 'a OR (b AND filtro)' — fura o
    filtro)."""
    conditions = [c for c in conditions if c is not None]
    if not conditions:
        return

    def _wrap(c):
        return exp.Paren(this=c) if isinstance(c, exp.Or) else c

    combined = _wrap(conditions[0])
    for c in conditions[1:]:
        combined = exp.And(this=combined, expression=_wrap(c))
    node.set("where", exp.Where(this=combined))


def _existing_where_conditions(node, drop_column: str | None = None) -> list:
    w = node.args.get("where")
    if w is None:
        return []
    out = []
    for c in _flatten_and(w.this):
        if drop_column and _pred_on_column(c, drop_column):
            continue
        out.append(c)
    return out


def _apply_filter(node, column: str, values: list[str], valid_columns: set[str]) -> bool:
    """AND-a (ou substitui) um predicado de segmento. Só atua se a coluna existe
    nas tabelas do slide. Retorna True se aplicou."""
    vals = [str(v) for v in (values or []) if v is not None and str(v) != ""]
    if not column or column.lower() not in valid_columns or not vals:
        return False
    col = exp.column(column)
    if len(vals) == 1:
        pred = exp.EQ(this=col, expression=exp.Literal.string(vals[0]))
    else:
        pred = exp.In(this=col, expressions=[exp.Literal.string(v) for v in vals])
    kept = _existing_where_conditions(node, drop_column=column)
    _set_where(node, kept + [pred])
    return True


def _temporal_literal(v, kind: str):
    if kind == "numeric":
        try:
            return exp.Literal.number(str(int(float(v))))
        except Exception:
            return exp.Literal.string(str(v))
    return exp.Literal.string(str(v))  # 'YYYY-MM-DD' — Postgres casta p/ date


def _apply_temporal_range(node, column: str, start, end, kind: str, valid_columns: set[str]) -> bool:
    """Injeta o intervalo temporal: `col BETWEEN start AND end` (ou `>=`/`<=` se
    só um lado). Independente por coluna. Só atua se a coluna existe no slide."""
    column = (column or "").strip()
    has_start = start not in (None, "")
    has_end = end not in (None, "")
    if not column or column.lower() not in valid_columns or not (has_start or has_end):
        return False
    col = exp.column(column)
    if has_start and has_end:
        pred = exp.Between(this=col, low=_temporal_literal(start, kind), high=_temporal_literal(end, kind))
    elif has_start:
        pred = exp.GTE(this=col, expression=_temporal_literal(start, kind))
    else:
        pred = exp.LTE(this=col, expression=_temporal_literal(end, kind))
    kept = _existing_where_conditions(node, drop_column=column)
    _set_where(node, kept + [pred])
    return True


def apply_temporal_to_sql(sql: str, temporal_ranges, accessible_tables=None,
                          login: str = "", apply_login_filter: bool = True):
    """Usado na GERAÇÃO: injeta os ranges temporais num SQL recém-gerado e
    reexecuta. Retorna (new_sql, data|None, err). data=None & err=None significa
    'nenhuma coluna do range existe neste slide' (caller mantém o original)."""
    if not temporal_ranges:
        return sql, None, None
    node = _parse(sql)
    if node is None:
        return sql, None, "SQL não pôde ser parseado."
    if not _is_simple_select(node):
        return sql, None, "Estrutura de SQL não suportada para filtro de período (UNION/CTE/subconsulta)."
    valid = _valid_columns_for(node)
    applied = False
    for tr in temporal_ranges:
        if _apply_temporal_range(node, tr.get("column"), tr.get("start"), tr.get("end"),
                                 (tr.get("kind") or "date"), valid):
            applied = True
    if not applied:
        return sql, None, None
    login_tables = set()
    if apply_login_filter and login:
        login_tables = {str(t).lower() for t in (get_tables_with_login_column(accessible_tables) or [])}
    _ensure_login_filter(node, login, login_tables)
    new_sql = _regenerate(node)
    data = execute_readonly_sql(new_sql)
    if isinstance(data, dict) and "error" in data:
        return new_sql, None, data.get("error")
    return new_sql, data, None


def _ensure_login_filter(node, login: str, login_tables: set[str]) -> None:
    tabs = _slide_tables(node)
    if not (login and login_tables and (tabs & login_tables)):
        return
    # já tem filtro de login?
    for c in _existing_where_conditions(node):
        if _pred_on_column(c, "login"):
            return
    pred = exp.EQ(this=exp.column("login"), expression=exp.Literal.string(login))
    _set_where(node, _existing_where_conditions(node) + [pred])


def _swap_window(node, window: str, valid_columns: set[str]) -> bool:
    """Troca o sufixo de janela das colunas-fonte (ex.: qt_recarga_12m -> _6m),
    apenas quando a coluna-alvo existe. Aliases de saída ficam. Retorna True se
    alterou algo."""
    if window not in _WINDOWS:
        return False
    changed = False
    for col in node.find_all(exp.Column):
        nm = col.name or ""
        m = _WIN_RE.match(nm)
        if not m:
            continue
        base, cur = m.group(1), m.group(2).lower()
        if cur == window:
            continue
        target = f"{base}_{window}"
        if target.lower() in valid_columns:
            col.set("this", exp.to_identifier(target, quoted=col.this.quoted if col.this else False))
            changed = True
    return changed


def _regenerate(node) -> str:
    return node.sql(dialect="postgres")


# ---------------------------------------------------------------------------
# Recuperar (column, agg) do herói para recompor determinístico
# ---------------------------------------------------------------------------

def _recover_hero_spec(hero: dict, chart_data: dict) -> tuple[str | None, str, bool]:
    """Descobre (column, agg, confiável) que reproduz o value_raw original.
    Decks novos guardam column/agg (confiável). Legados: casa o value_raw contra
    o chart_data salvo — confiável só quando o resultado NÃO foi truncado (a
    amostra é capada em 60 linhas; sum/avg sobre amostra truncada não bate).
    Sem confiança, o chamador pula o slide (não mostra número-herói errado)."""
    column = hero.get("column")
    agg = hero.get("agg")
    if column and agg in _VALID_AGGS:
        return column, agg, True
    cd = chart_data or {}
    cols = cd.get("columns") or []
    rows = cd.get("rows") or []
    rc = cd.get("row_count")
    truncated = bool(rc and rc > len(rows))
    target = _coerce_number(hero.get("value_raw"))
    if not cols or not rows:
        return (column or (cols[0] if cols else None)), (agg or "first"), False
    numeric = _numeric_columns(cols, rows)
    cands = numeric or cols
    if target is None:  # herói textual — 'first' só é seguro com 1 linha
        return (cands[0] if cands else None), "first", (len(rows) == 1)
    for c in cands:
        for a in ("first", "sum", "avg", "min", "max", "count"):
            try:
                v = _coerce_number(_compute_value(rows, c, a))
            except Exception:
                v = None
            if v is not None and abs(v - target) <= max(1e-6, abs(target) * 1e-4):
                conf = (a in ("first", "min", "max")) or not truncated
                return c, a, conf
    return (cands[0] if cands else None), ("first" if len(rows) == 1 else "sum"), False


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------

def analyze_deck_params(deck_spec: dict, accessible_tables=None) -> dict:
    """Extrai os 'botões' do deck: janelas presentes, tabelas e dimensões de
    recorte (colunas categóricas) com seus valores distintos."""
    _TABLE_COLS_CACHE.clear()
    slides = (deck_spec or {}).get("slides") or []
    tables: set[str] = set()
    windows: set[str] = set()
    for s in slides:
        if s.get("type") != "insight" or not s.get("sql"):
            continue
        node = _parse(s["sql"])
        if node is None:
            continue
        tables |= _slide_tables(node)
        for col in node.find_all(exp.Column):
            m = _WIN_RE.match(col.name or "")
            if m:
                windows.add(m.group(2).lower())
    if accessible_tables:
        allow = {str(t).lower() for t in accessible_tables}
        tables = {t for t in tables if t in allow}
    # Dimensões: colunas de texto das tabelas do deck (deduplicadas).
    seen: set[str] = set()
    dimensions = []
    for t in sorted(tables):
        for col in _table_text_columns(t):
            key = col.lower()
            if key in seen:
                continue
            seen.add(key)
            vals = _distinct_values(t, col, limit=50)
            if 1 <= len(vals) <= 50:  # só dimensões com cardinalidade tratável
                dimensions.append({"column": col, "table": t, "values": vals})
    return {
        "windows": [w for w in _WINDOWS if w in windows],
        "dimensions": dimensions,
        "temporal_columns": _temporal_columns_for(tables),
        "tables": sorted(tables),
    }


def _is_simple_select(node) -> bool:
    """Transformável com segurança: um único SELECT no topo, sem set-operation
    (UNION/INTERSECT/EXCEPT), sem CTE (WITH) e sem subconsultas. Garante que a
    injeção de WHERE (segmento + RLS de login) atinge a CONSULTA INTEIRA — sem
    bypass por ramos não-filtrados de UNION, corpos de CTE ou subqueries."""
    if not isinstance(node, exp.Select):
        return False
    if node.args.get("with"):
        return False
    if len(list(node.find_all(exp.Select))) != 1:  # nenhuma subconsulta aninhada
        return False
    if node.find(exp.Union) or node.find(exp.Intersect) or node.find(exp.Except):
        return False
    return True


def _replay_one_sql(sql: str, segment_filters, window, login, login_tables, allowed_tables=None,
                    temporal_ranges=None):
    """Aplica transforms a um SQL e reexecuta. Retorna (new_sql, data|None, applied_filters, error)."""
    node = _parse(sql)
    if node is None:
        return sql, None, [], "SQL não pôde ser parseado."
    # Autorização: para não-root (allowed_tables != None), o SQL só pode tocar
    # tabelas autorizadas — barra deck_spec forjado lendo tabelas alheias.
    if allowed_tables is not None:
        not_allowed = _slide_tables(node) - allowed_tables
        if not_allowed:
            return sql, None, [], f"Tabela(s) não autorizada(s): {', '.join(sorted(not_allowed))}."

    touches_login = bool(login_tables and (_slide_tables(node) & login_tables))
    need_transform = bool(segment_filters) or bool(window) or bool(temporal_ranges)

    if not _is_simple_select(node):
        # SQL complexo (UNION/CTE/subquery): modificar a WHERE não atingiria todos
        # os ramos → risco de bypass de filtro/RLS. Política segura:
        if touches_login:
            # Não dá p/ garantir o filtro de login em SQL complexo → não executa.
            return sql, None, [], "SQL com UNION/CTE/subconsulta sobre tabela com RLS por login não é reexecutável com segurança."
        if need_transform:
            return sql, None, [], "Estrutura de SQL não suportada para recorte/janela/período seguros (UNION/CTE/subconsulta)."
        # Sem transform e sem RLS de login: reexecução VERBATIM (o filtro de login
        # original, se houver, já está embutido no SQL gerado).
        data = execute_readonly_sql(sql)
        if isinstance(data, dict) and "error" in data:
            return sql, None, [], data.get("error")
        return sql, data, [], None

    # SELECT simples: transforma com segurança (WHERE atinge a consulta inteira).
    valid = _valid_columns_for(node)
    applied = []
    for f in segment_filters or []:
        col = (f.get("column") or "").strip()
        if _apply_filter(node, col, f.get("values") or [], valid):
            applied.append(col)
    for tr in temporal_ranges or []:
        if _apply_temporal_range(node, tr.get("column"), tr.get("start"), tr.get("end"),
                                 (tr.get("kind") or "date"), valid):
            applied.append((tr.get("column") or "").strip())
    if window and len(_slide_tables(node)) <= 1:  # swap de janela só em single-table
        _swap_window(node, window, valid)
    _ensure_login_filter(node, login, login_tables)
    new_sql = _regenerate(node)
    data = execute_readonly_sql(new_sql)
    if isinstance(data, dict) and "error" in data:
        return new_sql, None, applied, data.get("error")
    return new_sql, data, applied, None


def _recompute_insight(slide: dict, data: dict, new_sql: str) -> bool:
    """Recomputa herói/gráfico/lastro do slide a partir de linhas frescas, sem LLM.
    Atômico: só muta o slide (incl. sql) se o número-herói puder ser recomposto
    com CONFIANÇA. Retorna False (slide pulado) caso contrário — nunca exibe um
    número-herói potencialmente errado."""
    columns = data.get("columns") or []
    rows = _normalize_rows(columns, data.get("rows") or [])
    row_count = data.get("row_count") if data.get("row_count") is not None else len(rows)
    hero = dict(slide.get("hero") or {})
    had_number = _coerce_number(hero.get("value_raw")) is not None
    column, agg, confident = _recover_hero_spec(hero, slide.get("chart_data") or {})
    can_recompute = confident and column and column in columns
    # Só pula o slide quando o herói TINHA um número e não dá p/ recompor com
    # segurança (evita exibir número errado). Herói textual/sem número segue —
    # apenas o gráfico/lastro é atualizado.
    if had_number and not can_recompute:
        return False
    if can_recompute:
        fmt = hero.get("fmt") or "raw"
        value_raw = _compute_value(rows, column, agg)
        hero["value_raw"] = _json_safe(value_raw)
        hero["value"] = _format_value(value_raw, fmt) if value_raw is not None else "—"
        hero["column"] = column
        hero["agg"] = agg
    slide["hero"] = hero
    src = list(_tables_in_sql(new_sql, None))
    quality = _source_quality(src)
    slide["source"] = quality
    slide["confidence"] = _confidence(quality, row_count, hero)
    slide["chart"] = _chart_spec(columns, rows, hero)
    slide["chart_data"] = {"columns": columns, "rows": rows[:60], "row_count": row_count}
    slide["row_count"] = row_count
    slide["sql"] = new_sql
    slide.pop("replay_error", None)
    return True


def replay_deck(deck_spec: dict, *, segment_filters=None, window=None, temporal_ranges=None,
                user=None, accessible_tables=None, apply_login_filter: bool = True) -> dict:
    """Reexecuta o deck determinístico com recorte/janela/período. Muta uma cópia
    rasa dos slides e devolve o novo deck_spec com `_replay` de auditoria."""
    import copy
    _TABLE_COLS_CACHE.clear()  # frescor por requisição (schema pode ter mudado)
    deck = copy.deepcopy(deck_spec or {})
    slides = deck.get("slides") or []
    login = (user or {}).get("login", "") if user else ""
    login_tables = set()
    if apply_login_filter and login:
        login_tables = {str(t).lower() for t in (get_tables_with_login_column(accessible_tables) or [])}
    # None = root (irrestrito); set = não-root (só tabelas autorizadas).
    allowed_tables = ({str(t).lower() for t in accessible_tables}
                      if accessible_tables is not None else None)

    updated, skipped = [], []
    for s in slides:
        if s.get("type") != "insight" or not s.get("sql"):
            continue
        new_sql, data, applied, err = _replay_one_sql(
            s["sql"], segment_filters, window, login, login_tables, allowed_tables,
            temporal_ranges=temporal_ranges,
        )
        if err or data is None:
            s["replay_error"] = err or "Sem dados após reexecução."
            skipped.append({"key": s.get("key"), "title": s.get("title"), "reason": s["replay_error"]})
            continue
        if not _recompute_insight(s, data, new_sql):
            s["replay_error"] = "Número-herói não pôde ser recomposto com segurança (resultado original truncado)."
            skipped.append({"key": s.get("key"), "title": s.get("title"), "reason": s["replay_error"]})
            continue
        # Causal: reaplica transforms ao SQL causal e reexecuta (best-effort).
        if s.get("causal") and (s["causal"].get("sql")):
            _replay_causal(s, segment_filters, window, login, login_tables, allowed_tables,
                           temporal_ranges=temporal_ranges)
        updated.append(s.get("key"))

    _resync_sintese_callouts(deck)

    deck["_replay"] = {
        "segment_filters": segment_filters or [],
        "window": window or "",
        "temporal_ranges": temporal_ranges or [],
        "slides_updated": updated,
        "slides_skipped": skipped,
    }
    return deck


def _mark_causal_degraded(slide: dict, reason: str) -> None:
    """Sinaliza que o efeito causal NÃO foi reexecutado (mantém o original) — para
    o front avisar que aquele número é da versão anterior, não do recorte atual."""
    c = dict(slide.get("causal") or {})
    c["_degraded"] = True
    c["_degraded_reason"] = reason
    slide["causal"] = c


def _replay_causal(slide: dict, segment_filters, window, login, login_tables, allowed_tables=None,
                   temporal_ranges=None) -> None:
    """Reexecuta o backbone causal (PSM) com os mesmos transforms. Degrada para o
    causal original em qualquer fragilidade (filosofia do _attach_causal), mas
    SINALIZA a degradação (_degraded) para não passar número causal estável por
    reexecutado."""
    causal = slide.get("causal") or {}
    treatment = (causal.get("treatment") or "").strip()
    outcome = (causal.get("outcome") or "").strip()
    covs = [str(c).strip() for c in (causal.get("covariates") or []) if c]
    new_sql, data, _applied, err = _replay_one_sql(
        causal.get("sql", ""), segment_filters, window, login, login_tables, allowed_tables,
        temporal_ranges=temporal_ranges,
    )
    if err or data is None:
        return _mark_causal_degraded(slide, "Reexecução do SQL causal falhou.")
    cols = data.get("columns") or []
    if treatment not in cols or outcome not in cols:
        return _mark_causal_degraded(slide, "Colunas de tratamento/desfecho ausentes no recorte.")
    use_covs = [c for c in covs if c in cols]
    if not use_covs:
        return _mark_causal_degraded(slide, "Sem covariáveis válidas no recorte.")
    rows = _normalize_rows(cols, data.get("rows") or [])
    if len(rows) < 20:
        return _mark_causal_degraded(slide, f"Amostra insuficiente para PSM ({len(rows)} < 20).")
    if len(rows) > 4000:
        rows = rows[:4000]
    try:
        from app.services.analytics_service import run_causal_analysis
        out = run_causal_analysis(
            {"rows": rows}, "psm",
            {"treatment": treatment, "outcome": outcome, "covariates": use_covs},
        )
    except Exception:
        return _mark_causal_degraded(slide, "Erro ao rodar o PSM no recorte.")
    if not isinstance(out, dict) or out.get("error"):
        return _mark_causal_degraded(slide, "PSM retornou erro no recorte.")
    att_pct = out.get("att_pct")
    if att_pct is None or abs(float(att_pct)) > 500:
        return _mark_causal_degraded(slide, "Efeito implausível no recorte (descartado).")
    merged = dict(causal)
    merged.pop("_degraded", None)
    merged.pop("_degraded_reason", None)
    merged.update({
        "att": out.get("att"), "att_pct": att_pct,
        "p_value": out.get("p_value"), "significant": bool(out.get("significant")),
        "n_treated": out.get("n_treated"), "n_control": out.get("n_control"),
        "effect_label": (f"{'+' if float(att_pct) >= 0 else ''}{round(float(att_pct))}%"),
        "sql": new_sql,
    })
    slide["causal"] = merged


def narrate_slide(slide: dict) -> dict:
    """Re-narra UM slide a partir dos números ATUAIS (após replay) — não toca
    SQL nem herói. Reusa o LLM geral; degrada para o texto existente em falha."""
    slide = slide or {}
    hero = slide.get("hero") or {}
    cd = slide.get("chart_data") or {}
    base = {
        "narrative": slide.get("narrative", ""),
        "actions": slide.get("actions", []),
        "subtitle": slide.get("subtitle", ""),
        "narrative_source": "fallback_original",
    }
    try:
        from app.services.llm_factory import make_general_llm
        from langchain_core.messages import HumanMessage, SystemMessage
        import json as _json
    except Exception:
        return base
    try:
        sys = (
            "Você re-narra um slide de insight executivo a partir dos NÚMEROS já "
            "calculados (não invente números; use só os fornecidos). Responda APENAS "
            "um objeto JSON, em português do Brasil, sem texto ao redor."
        )
        sample = (cd.get("rows") or [])[:12]
        human = (
            f"Título: {slide.get('title','')}\n"
            f"Pergunta: {slide.get('nl_question','')}\n"
            f"Número-herói: {hero.get('value','')} ({hero.get('label','')})\n"
            f"Colunas: {cd.get('columns', [])}\n"
            f"Amostra (até 12 linhas): {_json.dumps(sample, ensure_ascii=False, default=str)}\n\n"
            "Devolva JSON: {\"narrative\":\"<2-3 frases, max ~320 chars, fiel aos números>\","
            "\"subtitle\":\"<subtítulo curto>\",\"actions\":[\"<ação 1>\",\"<ação 2>\",\"<ação 3>\"]}"
        )
        llm = make_general_llm(temperature=0.2)
        resp = llm.invoke([SystemMessage(content=sys), HumanMessage(content=human)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(text, list):
            text = " ".join(str(t) for t in text)
        text = str(text).strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        a, b = text.find("{"), text.rfind("}")
        if a == -1 or b == -1:
            return base
        out = _json.loads(text[a:b + 1])
        return {
            "narrative": str(out.get("narrative") or base["narrative"])[:320],
            "subtitle": str(out.get("subtitle") or base["subtitle"])[:140],
            "actions": [str(x) for x in (out.get("actions") or base["actions"])][:3],
            "narrative_source": "llm_fresh",
        }
    except Exception:
        return base


def _resync_sintese_callouts(deck: dict) -> None:
    """Re-sincroniza os callouts da síntese a partir dos heróis insight (por key)."""
    heroes = {}
    for s in deck.get("slides") or []:
        if s.get("type") == "insight" and s.get("key") and s.get("hero"):
            heroes["c:" + str(s["key"])] = s["hero"]
            heroes[str(s["key"])] = s["hero"]
    for s in deck.get("slides") or []:
        if s.get("type") != "sintese":
            continue
        for c in s.get("callouts") or []:
            h = heroes.get(str(c.get("key")))
            if h:
                c["value"] = h.get("value", c.get("value"))
                c["value_raw"] = h.get("value_raw", c.get("value_raw"))
