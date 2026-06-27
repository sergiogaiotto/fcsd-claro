"""Ajustes de runtime editáveis pelo Root (Configurações > Ajustes).

Persistidos em ``app_settings`` (key/value). Cada consumidor lê via ``get_setting(key)``
com cache de TTL curto (5s) — evita bater no banco a cada consulta e tolera os 2 workers
(cada um com seu cache; defasagem máxima ~5s após uma alteração). Só expõe o que é seguro
e útil mexer em runtime; tipos suportados: ``int`` e ``bool``.
"""
from __future__ import annotations

import time as _time
import threading as _threading

# Schema curado. Ordem = ordem de exibição. `group` agrupa visualmente na UI.
SETTINGS_SCHEMA = [
    {
        "key": "query_statement_timeout_seconds", "type": "int",
        "default": 60, "min": 5, "max": 600, "group": "Performance e limites",
        "label": "Timeout de consulta SQL (s)",
        "help": "Tempo máximo que uma consulta de leitura roda no banco antes de ser "
                "cancelada. Evita que um SQL pesado trave a aplicação. Vale para Consultar, "
                "Análise Executiva e Reportes.",
    },
    {
        "key": "max_upload_mb", "type": "int",
        "default": 20, "min": 1, "max": 200, "group": "Performance e limites",
        "label": "Tamanho máximo de upload (MB)",
        "help": "Limite do arquivo .xlsx enviado em Configurações > Tabelas.",
    },
    {
        "key": "sql_autocorrect_enabled", "type": "bool",
        "default": True, "group": "Comportamento do agente",
        "label": "Auto-correção de SQL (1 tentativa)",
        "help": "Quando o SQL gerado falha no banco, devolve o erro real ao modelo e "
                "re-executa uma vez (RLS-safe). Desligue para inspecionar o SQL original "
                "sem correção automática.",
    },
    {
        "key": "catalog_enrich_agent", "type": "bool",
        "default": True, "group": "Comportamento do agente",
        "label": "Enriquecer o prompt com o Catálogo de Dados",
        "help": "Inclui descrições, tipos semânticos, PII e joins/KPIs sugeridos do "
                "Catálogo no prompt do agente NL→SQL, para tabelas catalogadas. Aplica na "
                "próxima recriação do agente (ex.: após um upload).",
    },
    {
        "key": "llm_reasoning_effort", "type": "choice",
        "default": "medium", "options": ["low", "medium", "high"], "group": "Modelo (LLM)",
        "label": "Esforço de raciocínio padrão (gpt-oss-120b)",
        "help": "Profundidade de raciocínio do modelo nas consultas. 'high' pensa mais "
                "(melhor em perguntas complexas), porém mais lento e mais tokens. O Consultar "
                "tem o atalho '🧠 Raciocínio profundo' que força 'high' por pergunta.",
    },
    {
        "key": "llm_temperature", "type": "float",
        "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.1, "group": "Modelo (LLM)",
        "label": "Temperatura do modelo",
        "help": "0 = determinístico (recomendado — o mesmo modelo gera o SQL e a explicação, "
                "e SQL confiável precisa de temperatura baixa). Valores maiores variam mais as "
                "respostas, mas deixam o SQL menos previsível/reproduzível.",
    },
]
_SCHEMA_BY_KEY = {s["key"]: s for s in SETTINGS_SCHEMA}

_CACHE: dict = {}
_CACHE_AT = 0.0
_CACHE_TTL = 5.0
_LOCK = _threading.Lock()


def _ensure_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_settings ("
        "  key TEXT PRIMARY KEY,"
        "  value TEXT NOT NULL,"
        "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "  updated_by TEXT"
        ")"
    )


def _coerce(schema: dict, raw):
    t = schema["type"]
    if t == "bool":
        return str(raw).strip().lower() in ("1", "true", "t", "yes", "on", "sim")
    if t == "choice":
        s = str(raw).strip().lower()
        opts = [str(o).lower() for o in schema.get("options", [])]
        return s if s in opts else schema["default"]
    if t == "float":
        try:
            v = float(raw)
        except (TypeError, ValueError):
            return schema["default"]
        lo, hi = schema.get("min"), schema.get("max")
        if lo is not None:
            v = max(lo, v)
        if hi is not None:
            v = min(hi, v)
        return round(v, 4)
    # int
    try:
        v = int(raw)
    except (TypeError, ValueError):
        return schema["default"]
    lo, hi = schema.get("min"), schema.get("max")
    if lo is not None:
        v = max(lo, v)
    if hi is not None:
        v = min(hi, v)
    return v


def _load_raw() -> dict:
    from app.core.database import get_sync_connection
    conn = get_sync_connection()
    try:
        _ensure_table(conn)
        cur = conn.execute("SELECT key, value FROM app_settings")
        out = {}
        for row in cur.fetchall():
            d = dict(row)
            out[d["key"]] = d["value"]
        return out
    finally:
        conn.close()


def _refresh() -> dict:
    global _CACHE, _CACHE_AT
    raw = _load_raw()
    vals = {}
    for s in SETTINGS_SCHEMA:
        vals[s["key"]] = _coerce(s, raw[s["key"]]) if s["key"] in raw else s["default"]
    _CACHE = vals
    _CACHE_AT = _time.monotonic()
    return vals


def get_setting(key: str):
    """Valor efetivo de um ajuste (override do banco ou default), com cache TTL.
    Robusto: se o banco falhar, cai no default do schema."""
    now = _time.monotonic()
    if not _CACHE or (now - _CACHE_AT) > _CACHE_TTL:
        with _LOCK:
            if not _CACHE or (_time.monotonic() - _CACHE_AT) > _CACHE_TTL:
                try:
                    _refresh()
                except Exception:
                    pass
    if key in _CACHE:
        return _CACHE[key]
    return _SCHEMA_BY_KEY.get(key, {}).get("default")


def get_settings_for_ui() -> list:
    """Schema + valores atuais, para o painel Ajustes (Root)."""
    try:
        cur = _refresh()
    except Exception:
        cur = {s["key"]: s["default"] for s in SETTINGS_SCHEMA}
    fields = ("key", "type", "label", "help", "group", "min", "max", "default", "options", "step")
    return [{**{k: s.get(k) for k in fields}, "value": cur.get(s["key"], s["default"])}
            for s in SETTINGS_SCHEMA]


def set_settings(updates: dict, user_login: str = "") -> dict:
    """Persiste ajustes válidos (ignora chaves desconhecidas), coage para o tipo/limites
    e invalida o cache. Retorna o que foi de fato aplicado."""
    from app.core.database import get_sync_connection
    conn = get_sync_connection()
    applied = {}
    try:
        _ensure_table(conn)
        for key, raw in (updates or {}).items():
            s = _SCHEMA_BY_KEY.get(key)
            if not s:
                continue
            val = _coerce(s, raw)
            if s["type"] == "bool":
                stored = "1" if val else "0"
            else:
                stored = str(val)
            conn.execute(
                "INSERT INTO app_settings (key, value, updated_at, updated_by) "
                "VALUES (?, ?, CURRENT_TIMESTAMP, ?) "
                "ON CONFLICT (key) DO UPDATE SET "
                "  value = EXCLUDED.value, updated_at = CURRENT_TIMESTAMP, updated_by = EXCLUDED.updated_by",
                (key, stored, user_login or ""),
            )
            applied[key] = val
        conn.commit()
    finally:
        conn.close()
    try:
        _refresh()
    except Exception:
        pass
    return applied
