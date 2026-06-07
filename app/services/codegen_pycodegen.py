"""TDIA-CodeGen M2 — gerador Spec-Driven + Schema-Driven de código Python.

A geração é dirigida por uma Spec = (query, técnica, padrão, opções), composta a
partir de DOIS inventários governáveis (CRUD por Root/Admin):

  - Técnica (Strategy): fragmentos de runtime — `imports`, `setup`, `read`,
    `show`, `teardown`. Convenção: o resultado fica na variável `result`.
  - Padrão (Template Method): um template Jinja que encaixa os fragmentos da
    técnica + o `schema` (colunas tipadas) + as `options`.

Render em 2 passes num **SandboxedEnvironment** (autoescape OFF para código, mas
sandbox ON — templates são autorados só por papéis confiáveis, ainda assim
isolamos execução). O **schema** vem de um dry-run `SELECT * FROM (<q>) LIMIT 0`
lendo `cursor.description` → tipos exatos (Schema-Driven).
"""
from __future__ import annotations

import re
import json
from jinja2.sandbox import SandboxedEnvironment

from app.core.database import get_sync_connection, _validate_select_only_sql
from app.services.codegen_service import _embed_sql

# OID do Postgres → tipos por ecossistema (para código tipado / schema-aware).
_OID_TYPES = {
    16:   {"py": "bool", "pd": "boolean", "spark": "BooleanType"},
    20:   {"py": "int", "pd": "Int64", "spark": "LongType"},
    21:   {"py": "int", "pd": "Int64", "spark": "ShortType"},
    23:   {"py": "int", "pd": "Int64", "spark": "IntegerType"},
    700:  {"py": "float", "pd": "float32", "spark": "FloatType"},
    701:  {"py": "float", "pd": "float64", "spark": "DoubleType"},
    1700: {"py": "decimal.Decimal", "pd": "object", "spark": "DecimalType"},
    25:   {"py": "str", "pd": "string", "spark": "StringType"},
    1042: {"py": "str", "pd": "string", "spark": "StringType"},
    1043: {"py": "str", "pd": "string", "spark": "StringType"},
    1082: {"py": "datetime.date", "pd": "object", "spark": "DateType"},
    1114: {"py": "datetime.datetime", "pd": "datetime64[ns]", "spark": "TimestampType"},
    1184: {"py": "datetime.datetime", "pd": "datetime64[ns]", "spark": "TimestampType"},
    114:  {"py": "dict", "pd": "object", "spark": "StringType"},
    3802: {"py": "dict", "pd": "object", "spark": "StringType"},
    2950: {"py": "str", "pd": "string", "spark": "StringType"},
}
_DEFAULT_TYPE = {"py": "str", "pd": "object", "spark": "StringType"}

_FRAGS = ("imports", "setup", "read", "show", "teardown")


def _pyident(name: str) -> str:
    s = re.sub(r"\W", "_", str(name or "")).lower().strip("_")
    if not s or s[0].isdigit():
        s = "c_" + s
    return s


def resolve_schema(sql: str) -> list[dict]:
    """Dry-run `SELECT * FROM (<q>) LIMIT 0` → colunas+tipos exatos. Retorna []
    se não for um SELECT resolvível (ex.: script de escrita)."""
    inner = (sql or "").strip().rstrip(";").strip()
    if not inner:
        return []
    probe = f"SELECT * FROM (\n{inner}\n) AS _cg_schema LIMIT 0"
    if _validate_select_only_sql(probe):  # devolve mensagem de erro se não-SELECT
        return []
    conn = get_sync_connection()
    try:
        cur = conn.raw.cursor()
        cur.execute(probe)
        cols = []
        for d in (cur.description or []):
            name = getattr(d, "name", None) or d[0]
            oid = getattr(d, "type_code", None)
            if oid is None and len(d) > 1:
                oid = d[1]
            types = _OID_TYPES.get(oid, _DEFAULT_TYPE)
            cols.append({"name": name, "ident": _pyident(name), **types})
        return cols
    except Exception:
        return []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Inventário (loaders + seed)
# ---------------------------------------------------------------------------

def _row_to_dict(r):
    return dict(r) if not isinstance(r, dict) else r


def load_technique(key: str) -> dict | None:
    ensure_seeded()
    conn = get_sync_connection()
    try:
        r = conn.execute(
            "SELECT key, label, runtime, frag_imports, frag_setup, frag_read, frag_show, frag_teardown "
            "FROM codegen_techniques WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        return _row_to_dict(r) if r else None
    finally:
        conn.close()


def load_pattern(key: str) -> dict | None:
    ensure_seeded()
    conn = get_sync_connection()
    try:
        r = conn.execute(
            "SELECT key, label, template, compatible FROM codegen_patterns WHERE key = ? AND is_active = 1",
            (key,),
        ).fetchone()
        return _row_to_dict(r) if r else None
    finally:
        conn.close()


def list_inventory() -> dict:
    ensure_seeded()
    conn = get_sync_connection()
    try:
        techs = [_row_to_dict(r) for r in conn.execute(
            "SELECT key, label, runtime FROM codegen_techniques WHERE is_active = 1 ORDER BY label").fetchall()]
        pats = [_row_to_dict(r) for r in conn.execute(
            "SELECT key, label, compatible FROM codegen_patterns WHERE is_active = 1 ORDER BY label").fetchall()]
        return {"techniques": techs, "patterns": pats}
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _env() -> SandboxedEnvironment:
    return SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True)


def render_spec(sql: str, technique_key: str, pattern_key: str, options: dict | None) -> dict:
    tech = load_technique((technique_key or "pandas").lower())
    if not tech:
        return {"error": f"Técnica '{technique_key}' não encontrada."}
    pat = load_pattern((pattern_key or "script").lower())
    if not pat:
        return {"error": f"Padrão '{pattern_key}' não encontrado."}

    compatible = pat.get("compatible") or "*"
    if compatible != "*":
        try:
            allowed = json.loads(compatible)
        except Exception:
            allowed = [c.strip() for c in compatible.split(",") if c.strip()]
        if allowed and tech["key"] not in allowed:
            return {"error": f"Padrão '{pat['key']}' não é compatível com a técnica '{tech['key']}'."}

    schema = resolve_schema(sql)
    env = _env()
    ctx = {"schema": schema, "query": sql, "options": options or {}, "sql_literal": _embed_sql((sql or "").strip().rstrip(";").strip())}
    try:
        t = {f: env.from_string(tech.get("frag_" + f) or "").render(**ctx) for f in _FRAGS}
        code = env.from_string(pat["template"]).render(t=t, **ctx)
    except Exception as e:
        return {"error": f"Erro ao renderizar o template: {str(e).splitlines()[0] if str(e) else e}"}
    return {"code": code.strip() + "\n", "schema": schema, "technique": tech["key"], "pattern": pat["key"]}


# ---------------------------------------------------------------------------
# Seed (idempotente) — migra as 3 técnicas atuais para dados + padrão 'script'
# ---------------------------------------------------------------------------

_SEED_TECHNIQUES = [
    {
        "key": "pandas", "label": "pandas + psycopg2", "runtime": "python",
        "description": "Lê o resultado num DataFrame pandas via psycopg2.",
        "frag_imports": "import os\nimport pandas as pd\nimport psycopg2",
        "frag_setup": 'conn = psycopg2.connect(os.environ.get("DATABASE_URL", "postgresql://USUARIO:SENHA@HOST:5432/BANCO"))',
        "frag_read": "result = pd.read_sql_query(SQL, conn)",
        "frag_show": 'print(result.head(50).to_string(index=False))\nprint(f"\\n{len(result)} linha(s).")',
        "frag_teardown": "conn.close()",
    },
    {
        "key": "sqlalchemy", "label": "SQLAlchemy", "runtime": "python",
        "description": "Executa via SQLAlchemy Core e itera as linhas.",
        "frag_imports": "import os\nfrom sqlalchemy import create_engine, text",
        "frag_setup": 'engine = create_engine(os.environ.get("DATABASE_URL", "postgresql+psycopg2://USUARIO:SENHA@HOST:5432/BANCO"))\nconn = engine.connect()',
        "frag_read": "result = conn.execute(text(SQL)).fetchall()",
        "frag_show": 'for row in result[:50]:\n    print(dict(row._mapping))\nprint(f"\\n{len(result)} linha(s).")',
        "frag_teardown": "conn.close()",
    },
    {
        "key": "pyspark", "label": "PySpark (JDBC)", "runtime": "spark",
        "description": "Lê via JDBC para um DataFrame Spark. Requer o driver JDBC do Postgres.",
        "frag_imports": "import os\nfrom pyspark.sql import SparkSession",
        "frag_setup": 'spark = SparkSession.builder.appName("tdia-codegen").getOrCreate()',
        "frag_read": (
            "result = (\n"
            '    spark.read.format("jdbc")\n'
            '    .option("url", os.environ.get("JDBC_URL", "jdbc:postgresql://HOST:5432/BANCO"))\n'
            '    .option("query", SQL)\n'
            '    .option("user", os.environ.get("DB_USER", "USUARIO"))\n'
            '    .option("password", os.environ.get("DB_PASSWORD", "SENHA"))\n'
            '    .option("driver", "org.postgresql.Driver")\n'
            "    .load()\n"
            ")"
        ),
        "frag_show": 'result.show(50, truncate=False)\nprint(f"{result.count()} linha(s).")',
        "frag_teardown": "spark.stop()",
    },
]

_SCRIPT_TEMPLATE = '''{{ t.imports }}

SQL = """{{ sql_literal }}"""

{% if schema %}# Colunas detectadas: {{ schema | map(attribute='name') | join(', ') }}
{% endif %}

def main():
{{ t.setup | indent(4, true) }}
{{ t.read | indent(4, true) }}
{{ t.show | indent(4, true) }}
{% if t.teardown %}{{ t.teardown | indent(4, true) }}
{% endif %}    return result


if __name__ == "__main__":
    main()
'''

_SEED_PATTERNS = [
    {
        "key": "script", "label": "Script simples", "compatible": "*",
        "description": "Script top-to-bottom com função main() — equivalente ao gerador original.",
        "template": _SCRIPT_TEMPLATE,
    },
]

_seeded = False


def ensure_seeded():
    """Popula os inventários na primeira utilização, se vazios (idempotente)."""
    global _seeded
    if _seeded:
        return
    conn = get_sync_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM codegen_techniques").fetchone()
        count = n["n"] if isinstance(n, dict) else n[0]
        if count == 0:
            for t in _SEED_TECHNIQUES:
                conn.execute(
                    "INSERT INTO codegen_techniques (key, label, runtime, description, frag_imports, frag_setup, frag_read, frag_show, frag_teardown, created_by) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT (key) DO NOTHING",
                    (t["key"], t["label"], t["runtime"], t["description"], t["frag_imports"], t["frag_setup"], t["frag_read"], t["frag_show"], t["frag_teardown"], "seed"),
                )
        m = conn.execute("SELECT COUNT(*) AS n FROM codegen_patterns").fetchone()
        pcount = m["n"] if isinstance(m, dict) else m[0]
        if pcount == 0:
            for p in _SEED_PATTERNS:
                conn.execute(
                    "INSERT INTO codegen_patterns (key, label, description, template, compatible, created_by) "
                    "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (key) DO NOTHING",
                    (p["key"], p["label"], p["description"], p["template"], p["compatible"], "seed"),
                )
        conn.commit()
        _seeded = True
    except Exception:
        conn.rollback()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CRUD de Técnicas (M2.1) — autoria só por Root/Admin (require_admin nas rotas).
# Toda gravação valida que os fragmentos renderizam no sandbox e que a técnica
# gera Python válido com o padrão 'script' (ast.parse).
# ---------------------------------------------------------------------------

def validate_technique(data: dict) -> str | None:
    key = (data.get("key") or "").strip()
    if not re.fullmatch(r"[a-z0-9_]+", key):
        return "A chave deve ter só minúsculas, números e _ (ex.: 'polars')."
    env = _env()
    ctx = {"schema": [], "query": "SELECT 1", "options": {}, "sql_literal": "SELECT 1"}
    try:
        frags = {f: env.from_string(data.get("frag_" + f) or "").render(**ctx) for f in _FRAGS}
    except Exception as e:
        return f"Fragmento inválido (Jinja): {str(e).splitlines()[0]}"
    pat = load_pattern("script")
    if pat:
        try:
            code = env.from_string(pat["template"]).render(t=frags, **ctx)
            import ast
            ast.parse(code)
        except SyntaxError as e:
            return f"O código gerado não é Python válido: {e}"
        except Exception as e:
            return f"Erro ao validar: {str(e).splitlines()[0]}"
    return None


def list_techniques_full() -> list[dict]:
    ensure_seeded()
    conn = get_sync_connection()
    try:
        rows = conn.execute(
            "SELECT id, key, label, runtime, description, frag_imports, frag_setup, "
            "frag_read, frag_show, frag_teardown, is_active FROM codegen_techniques ORDER BY label"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def create_technique(data: dict, created_by: str = "") -> dict:
    err = validate_technique(data)
    if err:
        return {"error": err}
    from app.core.database import _exec_returning_id
    conn = get_sync_connection()
    try:
        tid = _exec_returning_id(
            conn,
            "INSERT INTO codegen_techniques (key, label, runtime, description, frag_imports, frag_setup, "
            "frag_read, frag_show, frag_teardown, created_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (data["key"].strip(), data.get("label", ""), data.get("runtime", "python"), data.get("description", ""),
             data.get("frag_imports", ""), data.get("frag_setup", ""), data.get("frag_read", ""),
             data.get("frag_show", ""), data.get("frag_teardown", ""), created_by),
        )
        conn.commit()
        return {"ok": True, "id": tid}
    except Exception as e:
        conn.rollback()
        msg = str(e).splitlines()[0] if str(e) else "erro"
        if "unique" in msg.lower() or "duplicate" in msg.lower():
            return {"error": f"Já existe uma técnica com a chave '{data.get('key')}'."}
        return {"error": f"Erro ao criar: {msg}"}
    finally:
        conn.close()


def update_technique(tid: int, data: dict) -> dict:
    err = validate_technique(data)
    if err:
        return {"error": err}
    conn = get_sync_connection()
    try:
        conn.execute(
            "UPDATE codegen_techniques SET label=?, runtime=?, description=?, frag_imports=?, frag_setup=?, "
            "frag_read=?, frag_show=?, frag_teardown=?, is_active=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (data.get("label", ""), data.get("runtime", "python"), data.get("description", ""),
             data.get("frag_imports", ""), data.get("frag_setup", ""), data.get("frag_read", ""),
             data.get("frag_show", ""), data.get("frag_teardown", ""), int(data.get("is_active", 1) or 0), tid),
        )
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


def delete_technique(tid: int) -> dict:
    conn = get_sync_connection()
    try:
        conn.execute("DELETE FROM codegen_techniques WHERE id = ?", (tid,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()
