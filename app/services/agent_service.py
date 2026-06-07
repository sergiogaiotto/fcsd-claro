"""
Quick Insights — Deep Agent Service

Architecture based on deepagents/examples/text-to-sql-agent:
- Uses OpenAI via langchain-openai
- SQLDatabaseToolkit from langchain-community for SQL tools
- LangGraph for agent orchestration with tool calling
- Progressive disclosure: AGENTS.md (always loaded) + skills/ (on-demand)
- Planning via structured system prompt with guardrails
- Row-level security: auto-filter by LOGIN column when present
"""

from typing import Annotated, TypedDict
from pathlib import Path
import re as _re

from duckdb import HTTPException
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from app.core.config import settings
from app.core.database import (
    engine,
    get_sync_connection,
    get_table_schema_text,
    execute_readonly_sql,
)
from app.services.llm_factory import (
    make_sql_llm,
    make_sql_fallback_llm,
    bind_tools_with_fallback,
)

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    sql_query: str
    query_result: dict
    analysis_type_id: int | None
    skill_ids: list[int] | None
    accessible_tables: list[str] | None
    login_filter_user: str
    login_filter_tables: list[str]


# ---------------------------------------------------------------------------
# Skills loader (progressive disclosure)
# ---------------------------------------------------------------------------

def _load_agents_md() -> str:
    path = settings.agents_md
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _load_skill(skill_name: str) -> str:
    path = settings.skills_dir / skill_name / "SKILL.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def _get_skills_summary() -> str:
    """[deprecated] Lista de skills do diretório skills/. Mantido para compat,
    mas não é mais usado no system prompt — substituído por _get_skills_level1_context()
    que cobre as skills do banco (fonte canônica). Evita duplicação no prompt."""
    skills_dir = settings.skills_dir
    summaries = []
    if skills_dir.exists():
        for skill_dir in sorted(skills_dir.iterdir()):
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                content = skill_md.read_text(encoding="utf-8")
                lines = content.split("\n")
                name = skill_dir.name
                description = ""
                for line in lines:
                    if line.startswith("description:"):
                        description = line.split(":", 1)[1].strip()
                        break
                summaries.append(f"- **{name}**: {description}")
    if summaries:
        return "## Available Skills\n" + "\n".join(summaries)
    return ""


def _get_custom_skills_context(skill_ids: list[int] | None = None) -> str:
    """Level 2 — Full procedural instructions for triggered/selected skills ONLY.
    Parses SKILL.md frontmatter and injects only the body (instructions)."""
    if not skill_ids:
        return ""
    try:
        from app.core.database import get_skill_by_id, _parse_skill_frontmatter
        skills = [s for sid in skill_ids if (s := get_skill_by_id(sid))]
    except Exception:
        return ""
    if not skills:
        return ""
    parts = ["## Skills Ativas — Instruções Procedurais (Level 2)"]
    parts.append("As skills abaixo foram carregadas. Aplique o conhecimento de cada uma ao responder.\n")
    for s in skills:
        content = s.get("content", "")
        # Extract body only (skip frontmatter metadata)
        parsed = _parse_skill_frontmatter(content)
        body = parsed["body"] or content

        parts.append(f"### Skill: {s['name']}")
        if s.get("description"):
            parts.append(f"*{s['description']}*\n")
        if body:
            parts.append(body)
        parts.append("")
    return "\n".join(parts)


def _get_skills_level1_context() -> str:
    """Level 1 — Lightweight metadata summary of ALL active skills (~30 tokens each).
    Always loaded in system prompt as a 'table of contents' for available expertise.
    Enables the agent to know what skills exist without consuming full context."""
    try:
        from app.core.database import get_active_skills
        skills = get_active_skills()
    except Exception:
        return ""
    if not skills:
        return ""
    parts = ["## Skills Disponíveis (Level 1 — metadata)"]
    for s in skills:
        triggers = s.get("triggers", [])
        triggers_str = f" [triggers: {', '.join(triggers[:5])}]" if triggers else ""
        parts.append(f"- **{s['name']}**: {s.get('description', '')}{triggers_str}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Skill Router — auto-detection by trigger keywords
# ---------------------------------------------------------------------------

def _skill_router(question: str, history: list[dict] | None = None) -> list[int]:
    """Stage 1 router: match question against skill triggers via keyword scoring.
    Returns up to 3 skill_ids sorted by relevance. No LLM call — pure keyword match.

    When *history* is provided, the LAST user turn is concatenated to the question
    (with reduced weight) so follow-ups like "agora agrupe por categoria" still
    inherit the topic of the previous turn."""
    import json as _json
    try:
        from app.core.database import get_active_skills
        skills = get_active_skills()
    except Exception:
        return []
    if not skills:
        return []

    question_lower = question.lower()
    question_words = set(_re.findall(r'\b\w{3,}\b', question_lower))

    # Inherit topic from the previous user turn (lower weight by joining text only)
    prev_words: set[str] = set()
    if history:
        for turn in reversed(history):
            if turn.get("role") == "user" and turn.get("content"):
                prev_words = set(_re.findall(r'\b\w{3,}\b', turn["content"].lower()))
                break

    scored = []
    for skill in skills:
        triggers = skill.get("triggers", [])
        if not triggers:
            continue

        score = 0
        for trigger in triggers:
            tl = trigger.lower()
            # Exact phrase match (multi-word trigger)
            if " " in tl and tl in question_lower:
                score += 3
            # Single-word exact match in question
            elif tl in question_words:
                score += 2
            # Partial: trigger is substring of a question word
            elif len(tl) >= 4 and any(tl in w for w in question_words):
                score += 1
            # Topic inheritance from previous turn (half weight)
            elif tl in prev_words:
                score += 1

        if score > 0:
            scored.append((skill["id"], score, skill.get("priority", 10)))

    # Sort by score desc, then priority desc
    scored.sort(key=lambda x: (-x[1], -x[2]))

    # Return top 3 max (phase transition safeguard — paper Li 2026)
    return [s[0] for s in scored[:3]]


# ---------------------------------------------------------------------------
# Analysis type config
# ---------------------------------------------------------------------------

def _get_analysis_config(analysis_type_id: int | None) -> dict:
    default = {
        "system_prompt": (
            "Você é um analista de dados especialista. Responda em português do Brasil. "
            "Gere SQL ANSI compatível com SQLite. Explique os resultados de forma clara."
        ),
        "guardrails_input": "",
        "guardrails_output": "",
    }
    if not analysis_type_id:
        return default
    conn = get_sync_connection()
    try:
        cursor = conn.execute(
            "SELECT system_prompt, guardrails_input, guardrails_output "
            "FROM analysis_types WHERE id = ?",
            (analysis_type_id,),
        )
        row = cursor.fetchone()
        if row:
            return {
                "system_prompt": row[0] or default["system_prompt"],
                "guardrails_input": row[1] or "",
                "guardrails_output": row[2] or "",
            }
        return default
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Build Deep Agent graph
# ---------------------------------------------------------------------------

def build_agent():
    # llm = ChatOpenAI(model=settings.openai_model,api_key=settings.openai_api_key,temperature=0,)
    llm = make_sql_llm(temperature=0)
    fallback_llm = make_sql_fallback_llm(temperature=0)
    
    db = SQLDatabase(engine=engine, sample_rows_in_table_info=3)
    toolkit = SQLDatabaseToolkit(db=db, llm=llm)
    sql_tools = toolkit.get_tools()
    # llm_with_tools = llm.bind_tools(sql_tools)
    llm_with_tools = bind_tools_with_fallback(
        llm,
        sql_tools,
        fallback_llm=fallback_llm,
    )
    
    agents_md = _load_agents_md()

    def agent_node(state: AgentState):
        config = _get_analysis_config(state.get("analysis_type_id"))
        accessible = state.get("accessible_tables")
        schema_text = get_table_schema_text(accessible)

        # Catalog enrichment: inject business context (descriptions, semantic
        # types, PII flags, suggested joins/KPIs) for the tables that have a
        # catalog entry. Tables without one fall back to the raw schema above.
        # Empty string → no cataloged table → prompt identical to legacy. Flag
        # CATALOG_ENRICH_AGENT can disable it without a code deploy.
        catalog_context = ""
        if getattr(settings, "catalog_enrich_agent", True):
            try:
                from app.services.catalog_service import build_catalog_context_text
                catalog_context = build_catalog_context_text(accessible)
            except Exception:
                catalog_context = ""
        catalog_section = (
            "## Catálogo de Dados — Contexto de Negócio\n"
            "Use as descrições, tipos semânticos e joins sugeridos abaixo como "
            "fonte de verdade sobre o significado das tabelas e colunas — "
            "prefira-os a inferir pelo nome. Tabelas não listadas aqui seguem "
            "apenas o schema estrutural acima.\n"
            f"{catalog_context}\n"
        ) if catalog_context else ""

        # Progressive Disclosure: Level 1 (all skills metadata) + Level 2 (selected only)
        skills_level1 = _get_skills_level1_context()
        custom_skills = _get_custom_skills_context(state.get("skill_ids"))

        # Fallback skills do filesystem: incluídos APENAS se não houver skill com
        # mesmo nome ativa no banco (evita duplicação de conteúdo no prompt).
        try:
            from app.core.database import get_active_skills
            db_skill_names = {s.get("name", "").lower() for s in get_active_skills()}
        except Exception:
            db_skill_names = set()

        fallback_parts = []
        if "query-writing" not in db_skill_names:
            qs = _load_skill("query-writing")
            if qs:
                fallback_parts.append("## Skill: Query Writing\n" + qs)
        if "schema-exploration" not in db_skill_names:
            ss = _load_skill("schema-exploration")
            if ss:
                fallback_parts.append("## Skill: Schema Exploration\n" + ss)
        fallback_skills = "\n\n".join(fallback_parts)

        # Build table restriction notice
        table_restriction = ""
        if accessible is not None:
            table_restriction = (
                f"\n## RESTRIÇÃO DE ACESSO\n"
                f"Você só pode consultar as seguintes tabelas: {', '.join(accessible)}\n"
                f"NÃO tente acessar tabelas fora desta lista.\n"
            )

        # ── Row-level security: login filter ──────────────────────
        login_filter = ""
        login_user = state.get("login_filter_user", "")
        login_tables = state.get("login_filter_tables", [])
        if login_user and login_tables:
            tables_csv = ", ".join(f'"{t}"' for t in login_tables)
            safe_login = login_user.replace("'", "''")
            login_filter = (
                f"\n## FILTRO OBRIGATÓRIO POR USUÁRIO — ROW-LEVEL SECURITY\n"
                f"As seguintes tabelas possuem a coluna \"login\": {tables_csv}\n"
                f"REGRA INVIOLÁVEL: Sempre que consultar qualquer uma dessas tabelas, "
                f"você DEVE obrigatoriamente incluir o filtro:\n"
                f"  WHERE \"login\" = '{safe_login}'\n"
                f"Se a query já tiver cláusula WHERE, use:\n"
                f"  AND \"login\" = '{safe_login}'\n"
                f"Aplica-se a SELECT direto, JOINs, subqueries, CTEs e qualquer "
                f"forma de acesso a essas tabelas.\n"
                f"NUNCA omita este filtro — é uma regra de segurança obrigatória.\n"
                f"NUNCA mostre dados de outros usuários.\n"
            )

        system_content = f"""{config['system_prompt']}

## Agent Identity
{agents_md}

{skills_level1}

{custom_skills}

{fallback_skills}

{table_restriction}

{login_filter}

## Current Database Schema
{schema_text}

{catalog_section}
## Guardrails de Entrada
{config['guardrails_input']}

## Guardrails de Saída
{config['guardrails_output']}
"""
        messages = [SystemMessage(content=system_content)] + state["messages"]
        response = llm_with_tools.invoke(messages)
        return {"messages": [response]}

    def should_continue(state: AgentState):
        last = state["messages"][-1]
        if hasattr(last, "tool_calls") and last.tool_calls:
            return "tools"
        return END

    tool_node = ToolNode(sql_tools)
    graph = StateGraph(AgentState)
    graph.add_node("agent", agent_node)
    graph.add_node("tools", tool_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_agent = None


def get_agent():
    global _agent
    if _agent is None:
        _agent = build_agent()
    return _agent


def reset_agent():
    global _agent
    _agent = None


# ---------------------------------------------------------------------------
# SQL LIMIT helper
# ---------------------------------------------------------------------------


def _apply_limit(sql: str, limit: int | None) -> str:
    pattern = _re.compile(r'\s*\bLIMIT\s+\d+\b', _re.IGNORECASE)
    if limit is None or limit <= 0:
        return pattern.sub('', sql)
    if pattern.search(sql):
        return pattern.sub(f' LIMIT {limit}', sql)
    stripped = sql.rstrip().rstrip(';').rstrip()
    return f"{stripped} LIMIT {limit}"


# ---------------------------------------------------------------------------
# Run query
# ---------------------------------------------------------------------------

async def run_query(
    question: str,
    analysis_type_id: int | None = None,
    context: str | None = None,
    history: list[dict] | None = None,
    result_limit: int | None = 20,
    user_login: str = "",
    skill_ids: list[int] | None = None,
    accessible_tables: list[str] | None = None,
    saved_sql: str | None = None,
    apply_login_filter: bool = True,
    max_history_turns: int = 4,
) -> dict:
    """Run a natural language query through the Deep Agent.

    If *saved_sql* is provided (from a previously saved question), the agent
    is skipped entirely — the SQL is executed directly, saving time and tokens.
    Falls back to the full agent flow if the saved SQL fails.

    When *apply_login_filter* is True and the user is not root, tables with
    a "login" column are automatically filtered to show only the current
    user's data (row-level security).

    *history* is a structured list of prior turns: [{"role": "user"|"assistant",
    "content": "...", "sql": "..." (opcional)}]. The last *max_history_turns*
    user/assistant pairs are forwarded to the agent as real HumanMessage /
    AIMessage objects. If absent, the legacy *context* string is used as a
    fallback for backward compatibility.
    """

    # ------------------------------------------------------------------
    # Row-level security: detect tables with LOGIN column
    # ------------------------------------------------------------------
    login_filter_user = ""
    login_filter_tables = []
    if apply_login_filter and user_login:
        from app.core.database import get_tables_with_login_column
        login_filter_tables = get_tables_with_login_column(accessible_tables)
        if login_filter_tables:
            login_filter_user = user_login

    # ------------------------------------------------------------------
    # Fast path: reuse saved SQL without invoking the LLM agent
    # ------------------------------------------------------------------
    if saved_sql and saved_sql.strip():
        # If login filter is needed but saved SQL doesn't contain it,
        # force the agent path so the directive is applied correctly.
        if login_filter_user and login_filter_tables:
            safe_login = login_filter_user.replace("'", "''")
            if safe_login.lower() not in saved_sql.lower():
                saved_sql = None  # force agent path with login filter directive

    if saved_sql and saved_sql.strip():
        sql_to_run = _apply_limit(saved_sql.strip(), result_limit)
        data = execute_readonly_sql(sql_to_run)

        if "error" not in data:
            # Success — log and return immediately
            conn = get_sync_connection()
            try:
                conn.execute(
                    "INSERT INTO query_history (question, sql_generated, result_summary, analysis_type_id) "
                    "VALUES (?, ?, ?, ?)",
                    (question, saved_sql, "(reuso de SQL salvo)", analysis_type_id),
                )
                conn.commit()
            finally:
                conn.close()

            return {
                "question": question,
                "sql_generated": saved_sql,
                "sql_no_limit": saved_sql,
                "explanation": "Consulta executada com o SQL salvo anteriormente.",
                "data": data,
            }
        # If saved SQL failed, fall through to the normal agent flow
        # (schema may have changed since the SQL was saved)

    # ------------------------------------------------------------------
    # Normal path: invoke the Deep Agent
    # ------------------------------------------------------------------

    # Skill Router: auto-detect relevant skills if none manually selected
    auto_skill_ids = []
    if not skill_ids:
        auto_skill_ids = _skill_router(question, history=history)
        if auto_skill_ids:
            skill_ids = auto_skill_ids

    agent = get_agent()

    messages = []

    # Preferred path: structured multi-turn history → real HumanMessage / AIMessage.
    # The previously-generated SQL is appended to the assistant turn so follow-ups
    # like "agora filtre só o último mês" can anchor on the prior query.
    if history:
        recent = [t for t in history if isinstance(t, dict) and t.get("content")]
        # Keep only the last N turns (user+assistant), preserving order
        if max_history_turns and len(recent) > max_history_turns * 2:
            recent = recent[-(max_history_turns * 2):]
        for turn in recent:
            role = turn.get("role")
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            if role == "user":
                messages.append(HumanMessage(content=content))
            elif role == "assistant":
                sql = (turn.get("sql") or "").strip()
                full = content
                if sql:
                    full = f"{content}\n\nSQL utilizado:\n```sql\n{sql}\n```"
                messages.append(AIMessage(content=full))
    elif context:
        # Legacy fallback: ainda aceita a string concatenada antiga, mas não
        # forja resposta do assistente — embute como nota explícita.
        messages.append(HumanMessage(
            content=f"[Notas de turnos anteriores — apenas para referência]\n{context}"
        ))

    messages.append(HumanMessage(content=question))

    run_config = {}
    if settings.langfuse_secret_key and settings.langfuse_public_key:
        try:
            from langfuse import Langfuse
            from langfuse.langchain import CallbackHandler
            Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            langfuse_handler = CallbackHandler()
            run_config = {
                "callbacks": [langfuse_handler],
                "metadata": {
                    "langfuse_user_id": user_login or "anonymous",
                    "langfuse_session_id": f"qi-{user_login}" if user_login else None,
                    "langfuse_tags": [f"user:{user_login}"] if user_login else [],
                    "source": "quick-insights",
                },
            }
        except Exception:
            pass

    result = agent.invoke(
        {
            "messages": messages,
            "sql_query": "",
            "query_result": {},
            "analysis_type_id": analysis_type_id,
            "skill_ids": skill_ids,
            "accessible_tables": accessible_tables,
            "login_filter_user": login_filter_user,
            "login_filter_tables": login_filter_tables,
        },
        config=run_config,
    )

    final_messages = result["messages"]
    ai_response = ""
    sql_generated = ""

    for msg in final_messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                if tc["name"] in ("sql_db_query", "execute_query", "query_database"):
                    sql_generated = tc["args"].get("query", tc["args"].get("sql", ""))
        if hasattr(msg, "content") and isinstance(msg.content, str):
            if not hasattr(msg, "tool_calls") or not msg.tool_calls:
                if msg.type == "ai" and msg.content.strip():
                    ai_response = msg.content

    data = {}
    if sql_generated:
        sql_to_run = _apply_limit(sql_generated, result_limit)
        data = execute_readonly_sql(sql_to_run)
        # Não mascarar erro — front exibe banner com data.error e o SQL
        # tentado (data.attempted_sql), em vez de cair em "tabela vazia"
        # silenciosa.
        if isinstance(data, dict) and "error" in data:
            data = {"error": data.get("error"), "attempted_sql": sql_to_run}

    conn = get_sync_connection()
    try:
        conn.execute(
            "INSERT INTO query_history (question, sql_generated, result_summary, analysis_type_id) "
            "VALUES (?, ?, ?, ?)",
            (question, sql_generated, ai_response[:500] if ai_response else "", analysis_type_id),
        )
        conn.commit()
    finally:
        conn.close()

    sql_no_limit = _apply_limit(sql_generated, 0) if sql_generated else ""

    return {
        "question": question,
        "sql_generated": sql_generated,
        "sql_no_limit": sql_no_limit,
        "explanation": ai_response,
        "data": data,
        "auto_skill_ids": auto_skill_ids,
    }
