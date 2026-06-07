"""TDIA-CodeGen — Copiloto de Dados (programação em linguagem natural).

Um agente conversacional que **propõe** SQL, código Python tipado e ações,
aterrado no ESCOPO e no CATÁLOGO do usuário. Princípio de segurança: o LLM só
propõe; a EXECUÇÃO de SQL continua passando pelo autorizador determinístico
(`codegen_service.execute_script`, via `/api/codegen/run`) — escopo, posse e
confirmação de destrutivas. O Python sai do motor tipado (`render_spec`,
dry-run read-only).

O modelo responde num ENVELOPE JSON validado aqui; `assist()` converte o
envelope em `actions` de 1 clique que o painel renderiza (Inserir / Executar /
Gerar Python / Salvar snippet). Reaproveita o `llm_factory` (Hub Claro
gpt-oss-120b + fallback Azure) e o grounding já existente do app.

Persistência das conversas: tabela `codegen_chats` (uma thread por linha,
mensagens em TEXT-JSON), escopada por dono.
"""
from __future__ import annotations

import re
import json
import asyncio

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.services.llm_factory import make_chat_llm
from app.services.codegen_service import get_user_scope
from app.services.codegen_pycodegen import render_spec, list_inventory
from app.core.database import get_sync_connection, get_all_tables, get_table_schema_text

_MAX_GROUND_TABLES = 60
_MAX_SCHEMA_TABLES = 40
_MAX_HISTORY_TURNS = 8


# ---------------------------------------------------------------------------
# Grounding — o que o copiloto "sabe" sobre o usuário
# ---------------------------------------------------------------------------

def _scoped_table_names(user: dict) -> list[str]:
    scope = get_user_scope(user)
    allowed = scope["allowed"]
    names = []
    for t in get_all_tables():
        nm = t.get("name")
        if not nm:
            continue
        if scope["root"] or (allowed is not None and nm.lower() in allowed):
            names.append(nm)
    return sorted(names)


def _inventory_text() -> str:
    try:
        inv = list_inventory()
    except Exception:
        return ""
    techs = ", ".join(t["key"] for t in inv.get("techniques", []))
    pats = []
    for p in inv.get("patterns", []):
        pats.append(f'{p["key"]} (compat: {p.get("compatible") or "*"})')
    return f"Técnicas disponíveis: {techs}\nPadrões disponíveis: {'; '.join(pats)}"


def _grounding(user: dict) -> str:
    names = _scoped_table_names(user)
    if not names:
        parts = ["Você ainda não tem tabelas atribuídas no seu escopo (DataMarts/DiamondLayers)."]
    else:
        shown = names[:_MAX_GROUND_TABLES]
        more = "" if len(names) <= _MAX_GROUND_TABLES else f" (+{len(names) - _MAX_GROUND_TABLES} outras)"
        parts = ["Tabelas no seu escopo: " + ", ".join(shown) + more]
        try:
            schema_text = get_table_schema_text(names[:_MAX_SCHEMA_TABLES])
            if schema_text:
                parts.append("ESQUEMA (tabela: colunas):\n" + schema_text)
        except Exception:
            pass
        try:
            from app.services.catalog_service import build_catalog_context_text
            catalog_text = build_catalog_context_text(names) or ""
            if catalog_text:
                parts.append("CATÁLOGO (contexto de negócio):\n" + catalog_text)
        except Exception:
            pass
    inv = _inventory_text()
    if inv:
        parts.append("INVENTÁRIO p/ gerar Python:\n" + inv)
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt + montagem das mensagens
# ---------------------------------------------------------------------------

_SYSTEM = """Você é o **Copiloto de Dados** do TDIA-CodeGen — um assistente de engenharia de dados embutido numa IDE de SQL. Fale SEMPRE em português do Brasil, de forma direta e técnica.

Você ajuda o engenheiro a: (a) gerar SQL Postgres a partir de linguagem natural; (b) explicar/revisar/documentar SQL; (c) corrigir erros de uma consulta; (d) gerar código Python tipado a partir do SQL (pandas/sqlalchemy/pyspark via técnicas×padrões); (e) propor criação de tabelas (CREATE) no escopo do usuário.

REGRAS:
- Gere SQL SOMENTE para as tabelas/colunas do escopo informado. Não invente tabelas/colunas. Se faltar contexto, pergunte ou explique no campo "reply".
- O dialeto é POSTGRES. Prefira 1 statement; scripts (CREATE/INSERT) são permitidos quando o usuário pede.
- Você NÃO executa nada. Você PROPÕE; a execução passa por um autorizador (escopo/posse/confirmação de destrutivas). Nunca afirme que "executei" ou que "a tabela foi criada".
- Para gerar Python, escolha "technique" e "pattern" VÁLIDOS do inventário e compatíveis entre si.

RESPONDA SOMENTE com UM objeto JSON (sem nenhum texto fora dele, sem cercas ```), exatamente neste formato:
{
  "reply": "explicação curta em PT-BR (markdown leve permitido)",
  "sql": "SQL proposto ou null",
  "run": false,
  "python": null,
  "snippet": null
}
- "sql": preencha ao propor consulta/script; senão null.
- "run": true APENAS quando o usuário claramente quer EXECUTAR agora.
- "python": {"technique":"<key>","pattern":"<key>"} quando o usuário quer gerar código Python; senão null.
- "snippet": {"name":"<nome curto>"} quando fizer sentido salvar o SQL como snippet; senão null."""


def _to_messages(user: dict, message: str, history: list | None, context: dict | None) -> list:
    msgs = [SystemMessage(content=_SYSTEM + "\n\n=== CONTEXTO DO USUÁRIO ===\n" + _grounding(user))]
    for turn in (history or [])[-_MAX_HISTORY_TURNS * 2:]:
        content = (turn.get("content") or "").strip()
        if not content:
            continue
        if (turn.get("role") or "").lower() == "assistant":
            msgs.append(AIMessage(content=content))
        else:
            msgs.append(HumanMessage(content=content))
    ctx = context or {}
    note = []
    cur_sql = (ctx.get("sql") or "").strip()
    last_err = (ctx.get("last_error") or "").strip()
    if cur_sql:
        note.append("SQL atual no editor:\n```sql\n" + cur_sql[:4000] + "\n```")
    if last_err:
        note.append("Último erro de execução: " + last_err[:800])
    block = message if not note else message + "\n\n[CONTEXTO DA IDE]\n" + "\n".join(note)
    msgs.append(HumanMessage(content=block))
    return msgs


def _parse_envelope(text: str) -> dict:
    """Tolerante: aceita JSON puro, JSON em cerca ```json, ou degrada o texto
    cru para o campo `reply` (vira uma resposta de chat normal)."""
    if not text:
        return {}
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\s*", "", t)
        t = re.sub(r"\s*```$", "", t).strip()
    try:
        obj = json.loads(t)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return {"reply": text.strip()}


def _valid_tech_pat(technique: str, pattern: str) -> tuple[str, str]:
    try:
        inv = list_inventory()
        tkeys = {t["key"] for t in inv.get("techniques", [])}
        pkeys = {p["key"] for p in inv.get("patterns", [])}
    except Exception:
        return technique, pattern
    return (technique if technique in tkeys else "pandas",
            pattern if pattern in pkeys else "script")


async def assist(user: dict, message: str, history: list | None, context: dict | None) -> dict:
    """Ponto de entrada do copiloto. Retorna {reply, sql, actions[]}."""
    message = (message or "").strip()
    if not message:
        return {"reply": "Escreva uma pergunta ou pedido para o copiloto.", "sql": "", "actions": []}
    try:
        llm = make_chat_llm(temperature=0, role="sql_toolkit")
        resp = await asyncio.to_thread(llm.invoke, _to_messages(user, message, history, context))
        text = getattr(resp, "content", None)
        if isinstance(text, list):  # alguns providers devolvem content em partes
            text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
        text = text if isinstance(text, str) else str(resp)
    except Exception as e:
        return {"reply": f"Não consegui falar com o modelo agora: {str(e).splitlines()[0]}",
                "sql": "", "actions": []}

    env = _parse_envelope(text)
    reply = (env.get("reply") or "").strip() or "Ok."
    sql = (env.get("sql") or "").strip()
    ctx = context or {}
    actions: list[dict] = []

    if sql:
        actions.append({"type": "insert_sql", "label": "Inserir no editor", "sql": sql})
        if env.get("run") is True:
            actions.append({"type": "run_sql", "label": "▶ Executar", "sql": sql})

    base_sql = sql or (ctx.get("sql") or "").strip()
    py = env.get("python")
    if isinstance(py, dict) and base_sql:
        technique, pattern = _valid_tech_pat((py.get("technique") or "pandas").lower(),
                                             (py.get("pattern") or "script").lower())
        try:
            r = render_spec(base_sql, technique, pattern, {})
        except Exception:
            r = {"error": "falha"}
        if "code" in r:
            actions.append({"type": "python", "label": f"Gerar Python ({technique}·{pattern})",
                            "code": r["code"], "filename": f"consulta_{technique}.py",
                            "technique": technique, "pattern": pattern})

    snip = env.get("snippet")
    if isinstance(snip, dict) and base_sql:
        nm = ((snip.get("name") or "consulta").strip() or "consulta")[:80]
        actions.append({"type": "save_snippet", "label": f"Salvar snippet '{nm}'",
                        "name": nm, "sql": base_sql})

    return {"reply": reply, "sql": sql, "actions": actions}


# ---------------------------------------------------------------------------
# Persistência das conversas (codegen_chats) — escopada por dono
# ---------------------------------------------------------------------------

def list_chats(user: dict) -> list[dict]:
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT id, title, updated_at FROM codegen_chats WHERE owner_id = ? "
            "ORDER BY updated_at DESC LIMIT 100",
            (user["id"],),
        ).fetchall()
        return [dict(r) if not isinstance(r, dict) else r for r in rows]
    finally:
        conn.close()


def get_chat(user: dict, cid: int) -> dict | None:
    conn = get_sync_connection()
    try:
        r = conn.execute("SELECT id, title, messages FROM codegen_chats WHERE id = ? AND owner_id = ?",
                         (cid, user["id"])).fetchone()
        if not r:
            return None
        d = dict(r) if not isinstance(r, dict) else r
        msgs = d.get("messages")
        if isinstance(msgs, str):
            try:
                msgs = json.loads(msgs)
            except Exception:
                msgs = []
        d["messages"] = msgs or []
        return d
    finally:
        conn.close()


def save_chat(user: dict, cid, title: str, messages: list) -> dict:
    payload = json.dumps(messages or [], ensure_ascii=False)
    title = ((title or "Nova conversa").strip() or "Nova conversa")[:120]
    conn = get_sync_connection()
    try:
        if cid:
            conn.execute(
                "UPDATE codegen_chats SET title = ?, messages = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ? AND owner_id = ?",
                (title, payload, cid, user["id"]),
            )
            conn.commit()
            return {"ok": True, "id": int(cid)}
        from app.core.database import _exec_returning_id
        new_id = _exec_returning_id(
            conn,
            "INSERT INTO codegen_chats (owner_id, title, messages) VALUES (?, ?, ?)",
            (user["id"], title, payload),
        )
        conn.commit()
        return {"ok": True, "id": new_id}
    finally:
        conn.close()


def delete_chat(user: dict, cid: int) -> dict:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM codegen_chats WHERE id = ? AND owner_id = ?", (cid, user["id"]))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
