"""
Análise Executiva — Número-herói auditável (P0).

Camada fina sobre o motor "fale com seus dados" (agent_service.run_query):
1. resolve UMA pergunta de negócio em SQL + dados + narrativa (com RLS por login
   e restrição por tabelas acessíveis, exatamente como /api/query);
2. extrai o "número-herói" do resultado — escolhido por um passo leve de LLM,
   mas SEMPRE computado em Python a partir dos dados reais (anti-alucinação:
   o LLM escolhe coluna/agregação/formato; o valor vem do dataset);
3. anexa o lastro: o SQL gerado, o nº de linhas, as tabelas-fonte e a completude
   do dado vinda do catálogo;
4. deriva um selo de confiança (Alta/Média/Baixa) a partir de catálogo +
   completude — e proíbe número de baixa confiança de virar "tese".

Reaproventa report_service (formatadores BR) e catalog_service (qualidade/PII),
sem tocar em nenhum dos dois.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.agent_service import run_query
from app.services.report_service import _format_value, _aggregate, _coerce_number
from app.services.catalog_service import tables_in_sql, get_catalog_context

# Vocabulário aceito — espelha report_service._format_value e _aggregate.
_VALID_FMTS = {
    "currency_brl", "number_2", "number_0", "number_k",
    "percent_2", "percent_0", "percent_raw", "percent_raw_sign", "raw",
}
_VALID_AGGS = {"first", "sum", "avg", "count", "min", "max"}

# Tokens (palavras inteiras) que denotam um valor percentual no nome da coluna,
# rótulo ou caption. Casamento por TOKEN (split em não-alfanumérico), não por
# substring — evita falsos positivos como "percentil"/"percurso"/"liftoff".
_PERCENT_TOKENS = {
    "taxa", "percent", "percentual", "percentuais", "pct", "share", "captura",
    "conversao", "conversão", "churn", "uplift", "lift",
    "participacao", "participação", "penetracao", "penetração",
}
_NUMBER_FMTS = {"number_2", "number_0", "number_k", "raw"}
_PCT_SPLIT_RE = re.compile(r"[^0-9a-zà-ú]+")


def _looks_percent(*texts) -> bool:
    blob = " ".join(str(t) for t in texts if t)
    if "%" in blob:
        return True
    toks = _PCT_SPLIT_RE.split(blob.lower())
    return any(t in _PERCENT_TOKENS for t in toks)


# ---------------------------------------------------------------------------
# Normalização de linhas (execute_readonly_sql pode devolver list[tuple] ou
# list[dict], como em report_service.render_report)
# ---------------------------------------------------------------------------

def _normalize_rows(columns: list[str], raw_rows: list) -> list[dict]:
    if not raw_rows:
        return []
    if isinstance(raw_rows[0], (list, tuple)):
        return [dict(zip(columns, r)) for r in raw_rows]
    if isinstance(raw_rows[0], dict):
        return list(raw_rows)
    # coluna única achatada
    if len(columns) == 1:
        return [{columns[0]: v} for v in raw_rows]
    return []


def _numeric_columns(columns: list[str], rows: list[dict]) -> list[str]:
    """Colunas em que a maioria dos valores não-nulos é numérica."""
    out = []
    sample = rows[:200]
    for c in columns:
        vals = [r.get(c) for r in sample if r.get(c) is not None]
        if not vals:
            continue
        num = sum(1 for v in vals if _coerce_number(v) is not None)
        if num >= max(1, int(0.6 * len(vals))):
            out.append(c)
    return out


def _json_safe(v: Any) -> Any:
    if v is None or isinstance(v, (int, float, str, bool)):
        return v
    return str(v)


def _guess_fmt(column: str, value: Any) -> str:
    """Heurística de formato quando o LLM não está disponível."""
    name = (column or "").lower()
    n = _coerce_number(value)
    if any(k in name for k in ("taxa", "perc", "%", "share", "captura", "conversao", "conversão", "churn", "lift")):
        if n is not None and -1.0 <= n <= 1.0:
            return "percent_2"
        return "percent_raw"
    if any(k in name for k in ("valor", "receita", "arpu", "ticket", "r$", "faturamento", "custo", "preco", "preço")):
        return "currency_brl"
    if n is not None and abs(n) >= 1000:
        return "number_k"
    if n is not None and float(n).is_integer():
        return "number_0"
    return "number_2"


# ---------------------------------------------------------------------------
# Extração do número-herói
# ---------------------------------------------------------------------------

def _compute_value(rows: list[dict], column: str, agg: str) -> Any:
    if not rows or not column:
        return None
    if agg == "first":
        return rows[0].get(column)
    values = [r.get(column) for r in rows]
    return _aggregate(values, agg)


def _llm_pick_hero(question, explanation, columns, numeric_cols, row_count, sample) -> dict | None:
    """Pede ao LLM para ESCOLHER (coluna/agg/fmt/rótulo) — nunca o valor.
    Retorna None em qualquer falha (caller usa fallback determinístico)."""
    try:
        from app.services.llm_factory import make_general_llm
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception:
        return None
    try:
        sys = (
            "Você seleciona o NÚMERO-HERÓI de um resultado de consulta para servir "
            "de manchete em um slide executivo. Responda APENAS com um objeto JSON, "
            "sem texto ao redor."
        )
        human = f"""Pergunta de negócio: {question}
Narrativa do analista: {explanation[:600]}
Colunas: {columns}
Colunas numéricas: {numeric_cols}
Total de linhas no resultado: {row_count}
Amostra (até 15 linhas): {json.dumps(sample[:15], ensure_ascii=False, default=str)}

Escolha UM número que melhor responde à pergunta. Devolva JSON:
{{"column":"<coluna numérica existente>","agg":"first|sum|avg|min|max|count","fmt":"currency_brl|number_2|number_0|number_k|percent_2|percent_0|percent_raw|percent_raw_sign|raw","label":"<rótulo curto, ex: captura média>","caption":"<uma frase curta explicando o número>"}}

Regras:
- agg "first" quando o resultado já é um único valor (1 linha).
- Se a coluna/rótulo denotar PERCENTUAL/taxa/participação/share/conversão/captura/churn, use SEMPRE um fmt percent_* (NUNCA number_*): percent_2 se for proporção 0-1 (ex 0,002 -> 0,20%); percent_raw (ou percent_0) se já estiver em escala 0-100 (ex 21 -> 21%, 8,4 -> 8,4%). currency_brl para valores em R$; number_k para grandes contagens; number_0/number_2 só para contagens/medidas que NÃO são percentuais.
- Escolha sempre uma coluna que existe. Não invente números."""
        llm = make_general_llm(temperature=0)
        resp = llm.invoke([SystemMessage(content=sys), HumanMessage(content=human)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(text, list):  # alguns provedores devolvem blocos
            text = " ".join(str(t) for t in text)
        text = text.strip()
        # remove cercas de código se houver
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        spec = json.loads(text[start:end + 1])
        return spec if isinstance(spec, dict) else None
    except Exception:
        return None


def _pick_hero(question, explanation, columns, rows) -> dict:
    row_count = len(rows)
    numeric_cols = _numeric_columns(columns, rows)

    # Sem dados ou sem coluna numérica: herói textual do primeiro valor.
    if not rows:
        return {"value_raw": None, "value_formatted": "—", "label": "Sem dados",
                "caption": "A consulta não retornou linhas.", "fmt": "raw",
                "agg": "first", "column": columns[0] if columns else ""}

    spec = _llm_pick_hero(question, explanation, columns, numeric_cols, row_count, rows)

    column = agg = fmt = None
    label = caption = ""
    if spec:
        column = spec.get("column") if spec.get("column") in columns else None
        agg = spec.get("agg") if spec.get("agg") in _VALID_AGGS else None
        fmt = spec.get("fmt") if spec.get("fmt") in _VALID_FMTS else None
        label = str(spec.get("label") or "").strip()
        caption = str(spec.get("caption") or "").strip()

    # Fallback determinístico (sem LLM ou escolha inválida)
    if not column:
        column = numeric_cols[0] if numeric_cols else (columns[0] if columns else "")
    if not agg:
        agg = "first" if row_count == 1 else ("sum" if column in numeric_cols else "first")
    value_raw = _compute_value(rows, column, agg)
    if not fmt:
        fmt = _guess_fmt(column, value_raw) if column in numeric_cols else "raw"
    if not label:
        label = column or "resultado"

    # Guard de percentual: o LLM às vezes escolhe um fmt de número cru (number_2)
    # para uma métrica claramente percentual ("percentual elegíveis" = 8,40), e o
    # heurístico _guess_fmt é pulado porque o fmt do LLM já é válido. Aqui, se o
    # rótulo/coluna/caption indicam percentual mas o fmt é número cru, coage para
    # um fmt percentual — garantindo o símbolo "%". NÃO usa a pergunta (texto livre
    # mencionando "taxa" não deve converter uma CONTAGEM) e só coage dentro de uma
    # faixa plausível de percentual (evita contagem 338200 virar "338.200%").
    if value_raw is not None and fmt in _NUMBER_FMTS and _looks_percent(label, column, caption):
        n = _coerce_number(value_raw)
        if n is not None:
            if -1.0 <= n <= 1.0:
                fmt = "percent_2"            # proporção 0-1 → ×100
            elif abs(n) <= 150.0:
                fmt = "percent_raw"          # já em escala 0-100
            # fora da faixa (contagem/escala grande): mantém o fmt de número

    # Guard SIMÉTRICO: o LLM às vezes marca percent_2/percent_0 (que pressupõem
    # proporção 0-1 e multiplicam por 100) para um valor que JÁ está em escala 0-100
    # (ex.: taxa de conversão = 100), gerando "10.000%" (100×100). Se o fmt multiplica
    # por 100 mas |valor| escapa da faixa de proporção, rebaixa para percent_raw (sem
    # ×100). Teto 1.5 preserva proporções >100% legítimas (1.05 = 105%) e não toca em 0-1.
    if value_raw is not None and fmt in ("percent_2", "percent_0"):
        n = _coerce_number(value_raw)
        if n is not None and abs(n) > 1.5:
            fmt = "percent_raw"

    value_formatted = _format_value(value_raw, fmt) if value_raw is not None else "—"
    return {
        "value_raw": _json_safe(value_raw),
        "value_formatted": value_formatted,
        "label": label,
        "caption": caption,
        "fmt": fmt,
        "agg": agg,
        "column": column,
        "is_numeric": column in numeric_cols,
    }


# ---------------------------------------------------------------------------
# Lastro: qualidade/completude das tabelas-fonte (via catálogo)
# ---------------------------------------------------------------------------

def _source_quality(src_tables: list[str]) -> dict:
    ctx = get_catalog_context(src_tables) if src_tables else {}
    if not ctx:
        return {"cataloged": False, "tables": src_tables or [],
                "min_completeness": None, "min_quality": None, "pii": False, "details": []}
    comps, quals, details, pii_any = [], [], [], False
    for t, info in ctx.items():
        q = info.get("quality_score")
        if isinstance(q, (int, float)):
            quals.append(q)
        col_comps = [c.get("completeness") for c in info.get("columns", [])
                     if isinstance(c.get("completeness"), (int, float))]
        tcomp = min(col_comps) if col_comps else None
        if tcomp is not None:
            comps.append(tcomp)
        t_pii = any(c.get("pii") for c in info.get("columns", []))
        pii_any = pii_any or t_pii
        details.append({"table": t, "domain": info.get("domain") or "",
                        "quality_score": q, "completeness": tcomp, "pii": t_pii})
    return {
        "cataloged": True,
        "tables": list(ctx.keys()),
        "min_completeness": min(comps) if comps else None,
        "min_quality": min(quals) if quals else None,
        "pii": pii_any,
        "details": details,
    }


def _confidence(quality: dict, row_count: int, hero: dict) -> dict:
    if not hero or hero.get("value_raw") is None:
        return {"level": "Baixa", "reason": "Não foi possível extrair um número-chave do resultado."}
    if row_count == 0:
        return {"level": "Baixa", "reason": "A consulta retornou 0 linhas."}
    comp = quality.get("min_completeness")
    qual = quality.get("min_quality")
    if not quality.get("cataloged"):
        return {"level": "Média",
                "reason": "Fonte sem catálogo — completude do dado não verificada."}
    if isinstance(comp, (int, float)) and comp < 70:
        return {"level": "Baixa", "reason": f"Completude do dado-fonte baixa ({int(comp)}%)."}
    if (comp is None or comp >= 90) and (qual is None or qual >= 70):
        return {"level": "Alta", "reason": "Fonte catalogada, com alta completude e qualidade."}
    return {"level": "Média", "reason": "Completude/qualidade do dado-fonte intermediárias."}


# ---------------------------------------------------------------------------
# Entrypoint público
# ---------------------------------------------------------------------------

async def build_hero(
    question: str,
    user: dict | None,
    accessible_tables: list[str] | None,
    apply_login_filter: bool,
) -> dict:
    """Resolve a pergunta e devolve o número-herói + lastro + confiança."""
    user_login = (user or {}).get("login", "") if user else ""
    result = await run_query(
        question=question,
        result_limit=0,  # análise quer o universo todo
        user_login=user_login,
        accessible_tables=accessible_tables,
        apply_login_filter=apply_login_filter,
    )
    data = result.get("data") or {}
    sql = result.get("sql_generated", "") or ""
    explanation = result.get("explanation", "") or ""

    if isinstance(data, dict) and "error" in data:
        return {
            "question": question,
            "error": data.get("error"),
            "attempted_sql": data.get("attempted_sql") or sql,
        }

    columns = data.get("columns") or []
    rows = _normalize_rows(columns, data.get("rows") or [])
    row_count = data.get("row_count") if isinstance(data, dict) and data.get("row_count") is not None else len(rows)

    hero = _pick_hero(question, explanation, columns, rows)
    src_tables = tables_in_sql(sql, accessible_tables)
    quality = _source_quality(src_tables)
    confidence = _confidence(quality, row_count, hero)

    # Anti-alucinação: número de baixa confiança não pode virar "tese".
    hero["eligible_as_thesis"] = confidence["level"] != "Baixa"

    return {
        "question": question,
        "hero": hero,
        "confidence": confidence,
        "sql": sql,
        "explanation": explanation,
        "row_count": row_count,
        "source": quality,
        "columns": columns,
        "preview_rows": [{k: _json_safe(v) for k, v in r.items()} for r in rows[:20]],
    }
