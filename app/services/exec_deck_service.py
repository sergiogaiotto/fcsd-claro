"""
Análise Executiva — Deck Composer (P1).

Transforma UMA pergunta de negócio em um deck executivo completo (estrutura
Minto/SCQA/So-What, espelhando o material de referência), pronto para render no
navegador e exportar em PPTX.

Pipeline:
  1. Storyline plan  — o LLM decompõe a pergunta numa árvore de perguntas-slide
     (1 panorama + N insights), ancorado no Catálogo de Dados.
  2. Resolve         — cada pergunta-slide passa pelo motor canônico
     agent_service.run_query (RLS por login + tabelas acessíveis); o número-herói
     é escolhido pelo LLM mas COMPUTADO em Python (anti-alucinação), e o gráfico
     é derivado deterministicamente dos dados.
  3. Narrador Minto  — síntese top-down sobre TODOS os achados: tese única,
     "o que os dados mostram", "implicação estratégica", pilares do So-What e as
     frentes da Estratégia. Guarda-corpo: a tese só cita números que existem.
  4. Governance      — KPIs/metas, ritual de gestão, papéis-donos e roadmap 60d.

Reaproveita exec_analysis_service (herói/lastro/confiança) e report_service
(formatadores BR). Sem novas dependências além do orquestrador.
"""

from __future__ import annotations

import json
import datetime as _dt
from typing import Any

from app.services.agent_service import run_query
from app.services.exec_analysis_service import (
    _normalize_rows, _numeric_columns, _pick_hero, _source_quality,
    _confidence, _json_safe,
)
from app.services.report_service import _coerce_number

_MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
          "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

_TEMPORAL_HINTS = ("mes", "mês", "data", "ano", "periodo", "período", "tempo",
                   "dia", "semana", "trimestre", "safra", "cohort", "coorte")


def _clean_narrative(text, max_chars: int = 320) -> str:
    """Encurta e limpa a narrativa de um slide: remove markdown (**, crases),
    colapsa quebras de linha/listas e trunca para ~2 frases. Evita que o
    explanation longo do LLM transborde a caixa do slide (HTML e PPTX)."""
    if not text:
        return ""
    import re as _re
    t = str(text).replace("**", "").replace("`", "")
    t = _re.sub(r"\s+", " ", t).strip()
    if len(t) <= max_chars:
        return t
    cut = t[:max_chars]
    last = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
    if last > 80:
        return cut[:last + 1]
    sp = cut.rfind(" ")
    return (cut[:sp] if sp > 80 else cut).rstrip() + "…"


# ---------------------------------------------------------------------------
# LLM helper — invoca o modelo geral e devolve JSON (ou None)
# ---------------------------------------------------------------------------

def _llm_json(system: str, human: str, temperature: float = 0.2) -> dict | None:
    try:
        from app.services.llm_factory import make_general_llm
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception:
        return None
    try:
        llm = make_general_llm(temperature=temperature)
        resp = llm.invoke([SystemMessage(content=system), HumanMessage(content=human)])
        text = resp.content if hasattr(resp, "content") else str(resp)
        if isinstance(text, list):
            text = " ".join(str(t) for t in text)
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text[:4].lower() == "json":
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            return None
        out = json.loads(text[start:end + 1])
        return out if isinstance(out, dict) else None
    except Exception:
        return None


def _catalog_text(accessible_tables: list[str] | None) -> str:
    try:
        from app.services.catalog_service import build_cockpit_catalog_context, get_catalog_context
        names = accessible_tables if accessible_tables is not None else list(get_catalog_context(None).keys())
        return build_cockpit_catalog_context(names) if names else ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# 1. Storyline plan
# ---------------------------------------------------------------------------

def _plan_storyline(question: str, catalog_text: str, n_insights: int) -> dict:
    sys = (
        "Você é um consultor estratégico (estilo McKinsey) que planeja um deck "
        "executivo a partir de dados. Responda APENAS com JSON."
    )
    human = f"""Pergunta de negócio do executivo: {question}

Catálogo de dados disponível (tabelas, colunas, KPIs):
{catalog_text or '(sem catálogo — infira pelos nomes das tabelas)'}

Planeje a espinha do deck. Gere 1 pergunta de PANORAMA (a métrica-síntese que responde diretamente à pergunta) e {n_insights} perguntas de INSIGHT que destrincham o porquê por dimensões diferentes (ex.: por canal, por tempo de base/cohort, por risco, por produto/bundle, por frequência).

Prefira perguntas cujo resultado seja uma TABELA pequena e agrupada (2 a 15 linhas, ex.: "captura de banda larga por canal") — boa para virar número-herói E gráfico. Use o vocabulário do catálogo.

Devolva JSON:
{{"title":"<título curto e executivo do deck>","questions":[{{"key":"panorama","section":"SÍNTESE","title":"<título do slide>","nl_question":"<pergunta em linguagem natural>"}},{{"key":"i1","section":"INSIGHT","title":"<título>","nl_question":"<pergunta>","effect":true,"causal":{{"treatment":"<coluna binária 0/1 ou 2 categorias, ex: usa_app>","outcome":"<coluna de desfecho 0/1 ou numérica, ex: comprou_bl>","covariates":["<confundidor, ex: tempo_de_base>","<ex: risco>"],"row_question":"<pergunta NL que retorne UMA LINHA POR CLIENTE/UNIDADE com EXATAMENTE essas colunas (tratamento, desfecho e confundidores) — dados em nível de linha, NÃO agregados>"}}}}]}}

Causalidade (opcional): marque "effect":true e preencha "causal" APENAS para insights que afirmam um EFEITO/lift (ex.: "o App eleva a conversão", "o bundle aumenta a venda casada"). Para insights descritivos, omita "effect"/"causal". Confundidores = variáveis que poderiam explicar o efeito sem ser a causa (tempo de base, risco, recarga, canal). No máximo 2 insights com "effect":true. A row_question deve nomear as colunas exatamente como em treatment/outcome/covariates.

Regras: exatamente 1 panorama + {n_insights} insights; nl_question objetiva e respondível por SQL; sem inventar tabelas que não existam no catálogo."""
    plan = _llm_json(sys, human, temperature=0.3)
    if not plan or not isinstance(plan.get("questions"), list) or not plan["questions"]:
        # Fallback: deck mínimo de 1 slide com a própria pergunta.
        return {
            "title": question[:80],
            "questions": [{"key": "panorama", "section": "SÍNTESE",
                           "title": "Panorama", "nl_question": question}],
        }
    # Sanitiza: garante chaves e limita o tamanho.
    qs = []
    for i, q in enumerate(plan["questions"][: n_insights + 1]):
        if not isinstance(q, dict) or not q.get("nl_question"):
            continue
        item = {
            "key": str(q.get("key") or f"s{i}"),
            "section": "SÍNTESE" if i == 0 else "INSIGHT",
            "title": str(q.get("title") or f"Insight {i}")[:90],
            "nl_question": str(q["nl_question"])[:400],
        }
        cz = q.get("causal")
        if i > 0 and isinstance(cz, dict) and cz.get("row_question") and cz.get("treatment") and cz.get("outcome"):
            item["causal"] = {
                "treatment": str(cz.get("treatment"))[:80],
                "outcome": str(cz.get("outcome"))[:80],
                "covariates": [str(c)[:80] for c in (cz.get("covariates") or [])][:6],
                "row_question": str(cz.get("row_question"))[:500],
            }
        qs.append(item)
    if not qs:
        qs = [{"key": "panorama", "section": "SÍNTESE", "title": "Panorama", "nl_question": question}]
    return {"title": str(plan.get("title") or question[:80])[:120], "questions": qs}


# ---------------------------------------------------------------------------
# 2. Resolve cada pergunta-slide
# ---------------------------------------------------------------------------

def _chart_spec(columns: list[str], rows: list[dict], hero: dict) -> dict | None:
    """Deriva um gráfico (barras/linha) determinístico a partir do resultado.
    Sem LLM e sem pandas — robusto para o export PPTX nativo."""
    if not rows or len(rows) < 2 or len(rows) > 40:
        return None
    numeric = _numeric_columns(columns, rows)
    categorical = [c for c in columns if c not in numeric]
    if not numeric or not categorical:
        return None
    x = categorical[0]
    y = hero.get("column") if hero.get("column") in numeric else numeric[0]
    pairs = []
    for r in rows[:15]:
        label = r.get(x)
        val = _coerce_number(r.get(y))
        if label is None:
            continue
        pairs.append((str(label), float(val) if val is not None else 0.0))
    if len(pairs) < 2:
        return None
    xl = x.lower()
    ctype = "line" if any(h in xl for h in _TEMPORAL_HINTS) else "bar"
    return {
        "type": ctype,
        "x_field": x,
        "y_field": y,
        "labels": [p[0] for p in pairs],
        "values": [p[1] for p in pairs],
    }


async def _resolve_slide(q: dict, user_login: str, accessible_tables, apply_login_filter) -> dict:
    result = await run_query(
        question=q["nl_question"],
        result_limit=0,
        user_login=user_login,
        accessible_tables=accessible_tables,
        apply_login_filter=apply_login_filter,
    )
    data = result.get("data") or {}
    sql = result.get("sql_generated", "") or ""
    explanation = result.get("explanation", "") or ""
    out = {
        "key": q["key"], "section": q["section"], "title": q["title"],
        "nl_question": q["nl_question"], "sql": sql, "narrative": _clean_narrative(explanation),
        "hero": None, "chart": None, "source": {}, "confidence": {},
        "row_count": 0, "error": None, "_causal_spec": q.get("causal"),
    }
    if isinstance(data, dict) and "error" in data:
        out["error"] = data.get("error")
        out["confidence"] = {"level": "Baixa", "reason": "A consulta falhou."}
        return out
    columns = data.get("columns") or []
    rows = _normalize_rows(columns, data.get("rows") or [])
    row_count = data.get("row_count") if isinstance(data, dict) and data.get("row_count") is not None else len(rows)
    hero = _pick_hero(q["nl_question"], explanation, columns, rows)
    src = list(_tables_in_sql(sql, accessible_tables))
    quality = _source_quality(src)
    conf = _confidence(quality, row_count, hero)
    hero["eligible_as_thesis"] = conf["level"] != "Baixa"
    out.update({
        "hero": hero,
        "chart": _chart_spec(columns, rows, hero),
        "source": quality,
        "confidence": conf,
        "row_count": row_count,
    })
    return out


def _tables_in_sql(sql, accessible_tables):
    try:
        from app.services.catalog_service import tables_in_sql
        return tables_in_sql(sql, accessible_tables) or []
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Causal Backbone — efeito causal (PSM) para insights de efeito, com guardrails
# ---------------------------------------------------------------------------

def _fmt_signed_pct(v) -> str | None:
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    return f"{'+' if n >= 0 else ''}{round(n)}%"


async def _attach_causal(spec: dict, user_login: str, accessible_tables, apply_login_filter) -> dict | None:
    """Estima o efeito causal (PSM) de um insight de efeito. Degrada para None em
    QUALQUER fragilidade (sem dados, colunas ausentes, amostra pequena, erro) —
    nunca fabrica um '+X% causal'. O número só aparece quando o método rodou."""
    treatment = (spec.get("treatment") or "").strip()
    outcome = (spec.get("outcome") or "").strip()
    covariates = [str(c).strip() for c in (spec.get("covariates") or []) if c]
    rq = (spec.get("row_question") or "").strip()
    if not (treatment and outcome and rq):
        return None
    res = await run_query(
        question=rq, result_limit=0, user_login=user_login,
        accessible_tables=accessible_tables, apply_login_filter=apply_login_filter,
    )
    data = res.get("data") or {}
    if not isinstance(data, dict) or "error" in data:
        return None
    cols = data.get("columns") or []
    if treatment not in cols or outcome not in cols:
        return None
    covs = [c for c in covariates if c in cols]
    if not covs:
        return None
    rows = _normalize_rows(cols, data.get("rows") or [])
    if len(rows) < 20:
        return None
    if len(rows) > 4000:  # limita o custo do matching O(treated×control)
        rows = rows[:4000]
    try:
        from app.services.analytics_service import run_causal_analysis
    except Exception:
        return None
    out = run_causal_analysis(
        {"rows": rows}, "psm",
        {"treatment": treatment, "outcome": outcome, "covariates": covs},
    )
    if not isinstance(out, dict) or out.get("error"):
        return None
    att_pct = out.get("att_pct")
    eff = _fmt_signed_pct(att_pct)
    # Guarda anti-artefato: efeito % implausível (baseline de controle ~0) costuma
    # ser ruído, não achado de board — melhor não exibir do que mostrar "+5000%".
    try:
        if eff is None or abs(float(att_pct)) > 500:
            return None
    except (TypeError, ValueError):
        return None
    sig = bool(out.get("significant"))
    n_t, n_c = out.get("n_treated"), out.get("n_control")
    try:
        p_txt = f"p={float(out.get('p_value')):.3f}"
    except (TypeError, ValueError):
        p_txt = ""
    caveat = (f"PSM · {treatment}→{outcome} · n={n_t}+{n_c} · {p_txt} · "
              f"{'significativo' if sig else 'não significativo'}")
    return {
        "method": "PSM", "effect_label": eff, "att_pct": out.get("att_pct"),
        "att": out.get("att"), "ci_lower": out.get("ci_lower"), "ci_upper": out.get("ci_upper"),
        "p_value": out.get("p_value"), "significant": sig,
        "n_treated": n_t, "n_control": n_c,
        "treatment": treatment, "outcome": outcome, "covariates": covs,
        "caveat": caveat, "sql": res.get("sql_generated", ""),
    }


# ---------------------------------------------------------------------------
# 3. Narrador Minto + 4. Governance
# ---------------------------------------------------------------------------

def _heroes_brief(resolved: list[dict]) -> str:
    lines = []
    for r in resolved:
        h = r.get("hero") or {}
        lines.append(
            f"- [{r['key']}] {r['title']}: {h.get('value_formatted','—')} "
            f"({h.get('label','')}) — {(r.get('narrative') or '')[:180]}"
        )
    return "\n".join(lines)


def _narrate_minto(question: str, resolved: list[dict], n_insights: int) -> dict:
    sys = (
        "Você é um sócio de consultoria que escreve a camada executiva de um deck "
        "em Pirâmide de Minto (tese no topo) e SCQA. Responda APENAS com JSON. "
        "GUARDA-CORPO: só cite números que aparecem na lista de achados fornecida; "
        "nunca invente percentuais ou valores."
    )
    insight_keys = [r["key"] for r in resolved if r["section"] == "INSIGHT"] or [r["key"] for r in resolved]
    human = f"""Pergunta de negócio: {question}

Achados (número-herói + narrativa de cada slide):
{_heroes_brief(resolved)}

Escreva a camada executiva. Devolva JSON:
{{
 "thesis":"<frase-tese única e governante, que todos os achados sustentam>",
 "o_que_mostram":["<bullet>","<bullet>","<bullet>"],
 "implicacao":["<bullet de implicação estratégica>","<bullet>","<bullet>"],
 "pilares":[{{"n":1,"title":"<ex: Timing>","text":"<frase>"}},{{"n":2,"title":"<ex: Canal>","text":"<frase>"}},{{"n":3,"title":"<ex: Produto>","text":"<frase>"}}],
 "frentes":[{{"n":1,"title":"<frente estratégica>","text":"<frase>"}},{{"n":2,"title":"..","text":".."}},{{"n":3,"title":"..","text":".."}},{{"n":4,"title":"..","text":".."}}],
 "insight_subtitles":{{ {", ".join(f'"{k}":"<subtítulo curto>"' for k in insight_keys)} }},
 "insight_actions":{{ {", ".join(f'"{k}":["<ação>","<ação>","<ação>"]' for k in insight_keys)} }}
}}

Tom: executivo, direto, acionável (português do Brasil). Cada bullet tem no máximo ~16 palavras."""
    out = _llm_json(sys, human, temperature=0.4) or {}
    return out


def _governance(question: str, resolved: list[dict], synthesis: dict) -> dict:
    sys = (
        "Você desenha a governança executiva (KPIs, ritual, donos e roadmap de 60 "
        "dias) a partir da estratégia. Responda APENAS com JSON. Use baselines "
        "reais dos achados quando existirem; não invente números."
    )
    frentes = synthesis.get("frentes") or []
    human = f"""Pergunta: {question}
Tese: {synthesis.get('thesis','')}
Frentes estratégicas: {json.dumps(frentes, ensure_ascii=False)}
Achados/baselines:
{_heroes_brief(resolved)}

Devolva JSON:
{{
 "metas":[{{"value":"<ex: 30%+ ou +20 bps ou 2x>","label":"<o que medir>"}} (3 a 4 itens)],
 "ritual":["<bullet de cadência/medição>","<bullet>","<bullet>"],
 "donos":[{{"role":"<ex: Dono CRM/Canais>","scope":"<responsabilidade>"}} (3 itens)],
 "roadmap":[{{"period":"0–15 dias","title":"<título do sprint>","bullets":["<ação>","<ação>","<ação>"]}},{{"period":"15–30 dias","title":"..","bullets":[".."]}},{{"period":"30–45 dias","title":"..","bullets":[".."]}},{{"period":"45–60 dias","title":"..","bullets":[".."]}}]
}}"""
    out = _llm_json(sys, human, temperature=0.4) or {}
    return out


# ---------------------------------------------------------------------------
# Assemble
# ---------------------------------------------------------------------------

def _date_label() -> str:
    now = _dt.datetime.now()
    return f"Material executivo | {_MESES[now.month]}/{now.year}"


def _assemble(question, plan, resolved, synthesis, governance, source_global) -> dict:
    thesis = synthesis.get("thesis") or (resolved[0]["hero"]["caption"] if resolved and resolved[0].get("hero") else "")
    insight_resolved = [r for r in resolved if r["section"] == "INSIGHT"] or resolved
    actions = synthesis.get("insight_actions") or {}
    subtitles = synthesis.get("insight_subtitles") or {}

    callouts = []
    for r in resolved:
        h = r.get("hero") or {}
        if h.get("value_formatted") and h["value_formatted"] != "—":
            callouts.append({"value": h["value_formatted"], "label": h.get("label", ""),
                             "value_raw": h.get("value_raw"), "fmt": h.get("fmt"), "key": r["key"]})
    callouts = callouts[:5]

    slides: list[dict] = []
    slides.append({"type": "cover", "title": plan.get("title") or question[:80],
                   "subtitle": thesis, "date_label": _date_label()})

    slides.append({
        "type": "sintese", "section": "SÍNTESE", "title": "Resumo executivo",
        "thesis": thesis, "callouts": callouts,
        "o_que_mostram": (synthesis.get("o_que_mostram") or [])[:3],
        "implicacao": (synthesis.get("implicacao") or [])[:3],
    })

    pilares = synthesis.get("pilares") or []
    if pilares:
        slides.append({"type": "sowhat", "section": "SO WHAT", "title": "Diagnóstico executivo",
                       "pilares": pilares[:3], "thesis": thesis})

    for r in insight_resolved:
        h = r.get("hero") or {}
        slides.append({
            "type": "insight", "section": "INSIGHT", "title": r["title"], "key": r["key"],
            "nl_question": r.get("nl_question", ""),
            "subtitle": subtitles.get(r["key"], ""),
            "narrative": r.get("narrative", ""),
            "hero": {"value": h.get("value_formatted", "—"), "label": h.get("label", ""),
                     "caption": h.get("caption", ""), "eligible": h.get("eligible_as_thesis", True),
                     "value_raw": h.get("value_raw"), "fmt": h.get("fmt")},
            "chart": r.get("chart"),
            "actions": (actions.get(r["key"]) or [])[:3],
            "confidence": r.get("confidence", {}),
            "causal": r.get("causal"),
            "sql": r.get("sql", ""),
            "source": r.get("source", {}),
        })

    frentes = synthesis.get("frentes") or []
    if frentes:
        slides.append({"type": "estrategia", "section": "ESTRATÉGIA", "title": "Estratégia proposta",
                       "frentes": frentes[:4]})

    roadmap = governance.get("roadmap") or []
    if roadmap:
        slides.append({"type": "roadmap", "section": "ROADMAP", "title": "Roadmap 60 dias",
                       "sprints": roadmap[:4]})

    if governance.get("metas") or governance.get("ritual") or governance.get("donos"):
        slides.append({"type": "kpis", "section": "GESTÃO", "title": "KPIs e governança",
                       "metas": (governance.get("metas") or [])[:4],
                       "ritual": (governance.get("ritual") or [])[:3],
                       "donos": (governance.get("donos") or [])[:3]})

    return {
        "title": plan.get("title") or question[:80],
        "subtitle": thesis,
        "thesis": thesis,
        "question": question,
        "date_label": _date_label(),
        "source_footer": _source_footer(source_global),
        "slides": slides,
        "n_slides": len(slides),
    }


def _source_footer(src: dict) -> str:
    tables = ", ".join(src.get("tables", [])[:4]) if src else ""
    base = "Fonte: " + (tables or "dados internos")
    comp = src.get("min_completeness") if src else None
    if isinstance(comp, (int, float)):
        base += f" | completude {int(comp)}%"
    return base + " | Análise interna"


# ---------------------------------------------------------------------------
# Deck Designer AI — regenerar um único insight
# ---------------------------------------------------------------------------

def _quick_actions(title: str, hero: dict, narrative: str) -> list[str]:
    sys = ("Você sugere ações executivas curtas e acionáveis. Responda APENAS com "
           "JSON {\"actions\":[\"...\",\"...\",\"...\"]}.")
    human = (f"Insight: {title}\nNúmero-herói: {hero.get('value_formatted', '')} "
             f"({hero.get('label', '')})\nNarrativa: {(narrative or '')[:300]}\n\n"
             "Dê 3 ações recomendadas (máx ~14 palavras cada).")
    out = _llm_json(sys, human, temperature=0.4) or {}
    acts = out.get("actions") or []
    return [str(x) for x in acts if x][:3]


async def resolve_single_slide(question, user, accessible_tables, apply_login_filter) -> dict:
    """Regenera UM insight (Deck Designer AI): resolve a pergunta e devolve o
    slide pronto (hero/chart/narrativa/ações/lastro). Mantém a auditabilidade
    (o número vem do SQL); ações são sugeridas por um passo leve de LLM."""
    user_login = (user or {}).get("login", "") if user else ""
    q = {"key": "adhoc", "section": "INSIGHT", "title": (question or "")[:90], "nl_question": question}
    r = await _resolve_slide(q, user_login, accessible_tables, apply_login_filter)
    if r.get("error") or not r.get("hero"):
        return {"error": r.get("error") or "A pergunta não retornou um número utilizável."}
    h = r.get("hero") or {}
    return {
        "title": r["title"], "nl_question": question,
        "narrative": r.get("narrative", ""),
        "hero": {"value": h.get("value_formatted", "—"), "label": h.get("label", ""),
                 "caption": h.get("caption", ""), "eligible": h.get("eligible_as_thesis", True),
                 "value_raw": h.get("value_raw"), "fmt": h.get("fmt")},
        "chart": r.get("chart"),
        "actions": _quick_actions(r["title"], h, r.get("narrative", "")),
        "confidence": r.get("confidence", {}),
        "sql": r.get("sql", ""),
        "source": r.get("source", {}),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

async def compose_deck(
    question: str,
    user: dict | None,
    accessible_tables: list[str] | None,
    apply_login_filter: bool,
    n_insights: int = 4,
    on_progress=None,
) -> dict:
    n_insights = max(2, min(5, int(n_insights or 4)))
    user_login = (user or {}).get("login", "") if user else ""

    def _emit(ev):
        if on_progress:
            try:
                on_progress(ev)
            except Exception:
                pass

    catalog_text = _catalog_text(accessible_tables)
    plan = _plan_storyline(question, catalog_text, n_insights)
    _emit({"phase": "plan", "total": len(plan.get("questions") or [])})

    resolved: list[dict] = []
    _total_q = len(plan["questions"])
    for _qi, q in enumerate(plan["questions"]):
        _emit({"phase": "resolve", "i": _qi + 1, "total": _total_q, "title": q.get("title", "")})
        try:
            resolved.append(await _resolve_slide(q, user_login, accessible_tables, apply_login_filter))
        except Exception as e:
            resolved.append({"key": q["key"], "section": q["section"], "title": q["title"],
                             "nl_question": q["nl_question"], "sql": "", "narrative": "",
                             "hero": None, "chart": None, "source": {}, "row_count": 0,
                             "confidence": {"level": "Baixa", "reason": f"Falha: {e}"}, "error": str(e)})

    ok = [r for r in resolved if not r.get("error") and r.get("hero")]
    if not ok:
        return {"error": "Nenhuma pergunta-slide retornou dados utilizáveis.",
                "attempted": [{"title": r["title"], "error": r.get("error")} for r in resolved],
                "question": question}

    # Causal Backbone: prova de efeito (PSM) para insights elegíveis (cap 2).
    causal_budget = 2
    for r in ok:
        if causal_budget <= 0:
            break
        spec = r.get("_causal_spec")
        if r.get("section") == "INSIGHT" and isinstance(spec, dict) and spec.get("row_question"):
            try:
                c = await _attach_causal(spec, user_login, accessible_tables, apply_login_filter)
            except Exception:
                c = None
            if c:
                r["causal"] = c
                causal_budget -= 1

    _emit({"phase": "synthesis"})
    synthesis = _narrate_minto(question, ok, n_insights)
    _emit({"phase": "governance"})
    governance = _governance(question, ok, synthesis)

    # Lastro global: une as tabelas-fonte de todos os slides resolvidos.
    all_tables = sorted({t for r in ok for t in (r.get("source", {}).get("tables") or [])})
    try:
        source_global = _source_quality(all_tables)
    except Exception:
        source_global = {"tables": all_tables}

    _emit({"phase": "assemble"})
    deck = _assemble(question, plan, ok, synthesis, governance, source_global)
    deck["generated_at"] = _dt.datetime.utcnow().isoformat() + "Z"
    return deck
