"""TDIA-CodeGen — autorizador e executor de scripts SQL (P1b).

Cada statement do script é classificado (verbo + tabelas) via sqlglot e
autorizado contra o conjunto de tabelas do usuário ANTES de qualquer execução:

  - SELECT/INSERT/UPDATE/DELETE/TRUNCATE → tabelas no conjunto autorizado do
    usuário (DataMarts + DiamondLayers atribuídos + tabelas criadas por ele).
  - CREATE → permitido; a nova tabela é associada a um DataMart e registrada
    como de posse do usuário (tag 'tech' = presença em codegen_tables).
  - ALTER/DROP → apenas em tabelas de posse do usuário.
  - Qualquer outro comando (COPY, GRANT, SET, EXPLAIN, ...) → negado.

Execução é atômica (uma transação; rollback em qualquer erro/negação) e roda no
cursor psycopg cru — para não sofrer a tradução ?→%s do db_engine, que quebraria
operadores Postgres legítimos como `jsonb ? key`.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from app.core.database import (
    get_sync_connection, get_user_datamarts, get_user_diamond_layers,
    get_tables_for_datamarts, get_tables_for_diamond_layers,
)
from app.core.security import is_root

_READ = {"Select"}
_WRITE = {"Insert", "Update", "Delete", "TruncateTable"}
_OWNED_DDL = {"Drop", "Alter"}
_ALWAYS_DESTRUCTIVE = {"Drop", "TruncateTable"}
_SUPPORTED = _READ | _WRITE | _OWNED_DDL | {"Create"}


def _norm(name) -> str:
    return (str(name) if name is not None else "").strip().strip('"').lower()


def _stmt_tables(stmt) -> set[str]:
    """Tabelas reais referenciadas, excluindo aliases de CTE."""
    ctes = {_norm(c.alias) for c in stmt.find_all(exp.CTE)}
    tables = {_norm(t.name) for t in stmt.find_all(exp.Table) if t.name}
    return {t for t in tables if t and t not in ctes}


def _target_table(stmt) -> str | None:
    """Tabela-alvo de CREATE/DROP/ALTER (a que está sendo criada/alterada)."""
    t = stmt.this
    if isinstance(t, exp.Schema):
        t = t.this
    if isinstance(t, exp.Table):
        return _norm(t.name)
    return _norm(getattr(t, "name", "")) or None


def analyze(sql: str) -> list[dict]:
    """Parse o script em statements classificados. Lança ValueError se o SQL é
    inválido ou contém um comando não suportado."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except Exception as e:
        raise ValueError(f"SQL inválido: {e}")
    if not statements:
        raise ValueError("Consulta vazia.")
    infos = []
    for stmt in statements:
        verb = type(stmt).__name__
        if verb not in _SUPPORTED:
            raise ValueError(f"Comando não suportado no módulo: {verb.upper()}.")
        target = _target_table(stmt) if verb in ("Create", "Drop", "Alter") else None
        destructive = verb in _ALWAYS_DESTRUCTIVE
        if verb in ("Delete", "Update") and stmt.args.get("where") is None:
            destructive = True
        infos.append({
            "verb": verb,
            "tables": _stmt_tables(stmt),
            "target": target,
            "destructive": destructive,
            "expr": stmt,
        })
    return infos


def _owned_tables(user_id: int) -> set[str]:
    conn = get_sync_connection()
    try:
        cur = conn.execute("SELECT table_name FROM codegen_tables WHERE owner_id = ?", (user_id,))
        out = set()
        for r in cur.fetchall():
            out.add(_norm(r["table_name"] if isinstance(r, dict) else r[0]))
        return out
    except Exception:
        return set()
    finally:
        conn.close()


def get_user_scope(user: dict) -> dict:
    """Conjuntos de tabelas do usuário. root=True → acesso total (allowed=None)."""
    owned = _owned_tables(user["id"])
    if is_root(user):
        return {"root": True, "allowed": None, "owned": owned}
    dm_ids = [d["id"] for d in get_user_datamarts(user["id"])]
    dl_ids = [l["id"] for l in get_user_diamond_layers(user["id"])]
    allowed = set(map(_norm, get_tables_for_datamarts(dm_ids)))
    allowed |= set(map(_norm, get_tables_for_diamond_layers(dl_ids)))
    allowed |= owned
    return {"root": False, "allowed": allowed, "owned": owned}


def authorize(infos: list[dict], scope: dict) -> tuple[bool, str | None, bool, bool]:
    """Retorna (ok, erro, has_writes, has_creates). Nega o script inteiro se
    qualquer statement falhar (atômico)."""
    root = scope["root"]
    allowed = scope["allowed"]
    owned = scope["owned"]
    has_writes = has_creates = False

    def ok_read(t: str) -> bool:
        return root or (allowed is not None and t in allowed)

    for info in infos:
        verb, tables, target = info["verb"], info["tables"], info["target"]
        if verb == "Select":
            bad = sorted(t for t in tables if not ok_read(t))
            if bad:
                return False, f"Sem acesso de leitura à(s) tabela(s): {', '.join(bad)}.", has_writes, has_creates
        elif verb in _WRITE:
            has_writes = True
            bad = sorted(t for t in tables if not ok_read(t))
            if bad:
                return False, f"Sem acesso à(s) tabela(s): {', '.join(bad)}.", has_writes, has_creates
        elif verb == "Create":
            has_writes = has_creates = True
            sources = sorted(t for t in tables if t != target and not ok_read(t))
            if sources:
                return False, f"Sem acesso de leitura à(s) tabela(s)-fonte: {', '.join(sources)}.", has_writes, has_creates
        elif verb in _OWNED_DDL:
            has_writes = True
            if not target:
                return False, f"Não identifiquei a tabela do comando {verb.upper()}.", has_writes, has_creates
            if not (root or target in owned):
                return False, (f"{verb.upper()} só é permitido em tabelas criadas por você no módulo "
                               f"(a tabela '{target}' não consta como sua)."), has_writes, has_creates
    return True, None, has_writes, has_creates


def execute_script(sql: str, user: dict, target_datamart_id: int | None = None,
                   confirm: bool = False, result_limit: int = 100) -> dict:
    """Autoriza e executa o script. Retorna um dos formatos:
      {error}                      — negado/erro (HTTP 400 na rota)
      {needs_confirm, destructive_ops} — aguarda confirm=True
      {columns, rows, row_count, writes, limited} — quando há SELECT final
      {ok, writes, affected, message}             — escrita sem retorno
    """
    try:
        infos = analyze(sql)
    except ValueError as e:
        return {"error": str(e)}

    scope = get_user_scope(user)
    ok, err, has_writes, has_creates = authorize(infos, scope)
    if not ok:
        return {"error": err}

    if any(i["destructive"] for i in infos) and not confirm:
        return {"needs_confirm": True,
                "destructive_ops": [i["verb"].upper() for i in infos if i["destructive"]]}

    if has_creates and not scope["root"] and not target_datamart_id:
        return {"error": "Selecione o DataMart de destino (campo DataMart) para executar um CREATE."}

    limit = max(1, min(int(result_limit or 100), 5000))
    last = len(infos) - 1
    conn = get_sync_connection()
    raw = conn.raw
    cur = raw.cursor()
    final = None
    affected = 0
    try:
        for idx, info in enumerate(infos):
            expr = info["expr"]
            if info["verb"] == "Select" and idx == last and expr.args.get("limit") is None:
                expr = expr.limit(limit)
            cur.execute(expr.sql(dialect="postgres"))
            if info["verb"] == "Select" and idx == last:
                cols = [d[0] for d in cur.description] if cur.description else []
                final = {"columns": cols, "rows": [dict(r) for r in cur.fetchall()]}
                final["row_count"] = len(final["rows"])
            elif info["verb"] in _WRITE:
                try:
                    affected += max(cur.rowcount, 0)
                except Exception:
                    pass
        # pós-execução: registrar posse de CREATEs e limpar DROPs
        for info in infos:
            if info["verb"] == "Create" and info["target"]:
                _register(cur, info["target"], user["id"], target_datamart_id)
            elif info["verb"] == "Drop" and info["target"]:
                _unregister(cur, info["target"])
        raw.commit()
    except Exception as e:
        raw.rollback()
        conn.close()
        msg = str(e).splitlines()[0] if str(e) else "erro desconhecido"
        return {"error": f"Erro na execução: {msg}"}
    conn.close()

    _log_history(user, sql, has_writes, final, affected)

    if final is not None:
        final["writes"] = has_writes
        final["limited"] = final["row_count"] >= limit
        return final
    return {"ok": True, "writes": has_writes, "affected": affected,
            "message": (f"Script executado — {affected} linha(s) afetada(s)." if has_writes
                        else "Script executado.")}


def _register(cur, table_name: str, owner_id: int, datamart_id: int | None):
    cur.execute(
        "INSERT INTO codegen_tables (table_name, owner_id, datamart_id) VALUES (%s, %s, %s) "
        "ON CONFLICT (table_name) DO UPDATE SET owner_id = EXCLUDED.owner_id, datamart_id = EXCLUDED.datamart_id",
        (table_name, owner_id, datamart_id),
    )
    if datamart_id:
        cur.execute(
            "INSERT INTO datamart_tables (datamart_id, table_name) VALUES (%s, %s) "
            "ON CONFLICT (datamart_id, table_name) DO NOTHING",
            (datamart_id, table_name),
        )


def _unregister(cur, table_name: str):
    cur.execute("DELETE FROM codegen_tables WHERE LOWER(table_name) = %s", (table_name,))
    cur.execute("DELETE FROM datamart_tables WHERE LOWER(table_name) = %s", (table_name,))


def _log_history(user: dict, sql: str, has_writes: bool, final, affected: int = 0):
    """Registra a execução no histórico ISOLADO do módulo (codegen_runs) — não
    polui o query_history do app principal."""
    conn = get_sync_connection()
    try:
        rc = final["row_count"] if final else affected
        conn.execute(
            "INSERT INTO codegen_runs (user_id, sql, kind, row_count) VALUES (?, ?, ?, ?)",
            (user["id"], sql, "write" if has_writes else "read", rc),
        )
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# P3 — geração de código Python a partir do SQL (templates de string; injeção
# crua e segura — Jinja com autoescape estragaria o código).
# ---------------------------------------------------------------------------

_PANDAS_TPL = '''# Gerado pelo TDIA-CodeGen — pandas + psycopg2
# Conexao via variavel de ambiente DATABASE_URL, ex.:
#   export DATABASE_URL="postgresql://usuario:senha@host:5432/banco"
import os
import pandas as pd
import psycopg2

SQL = """___SQL___"""


def main():
    dsn = os.environ.get("DATABASE_URL", "postgresql://USUARIO:SENHA@HOST:5432/BANCO")
    conn = psycopg2.connect(dsn)
    try:
        df = pd.read_sql_query(SQL, conn)
    finally:
        conn.close()
    print(df.head(50).to_string(index=False))
    print(f"\\n{len(df)} linha(s).")
    return df


if __name__ == "__main__":
    main()
'''

_SQLALCHEMY_TPL = '''# Gerado pelo TDIA-CodeGen — SQLAlchemy
# Conexao via variavel de ambiente DATABASE_URL, ex.:
#   export DATABASE_URL="postgresql+psycopg2://usuario:senha@host:5432/banco"
import os
from sqlalchemy import create_engine, text

SQL = """___SQL___"""


def main():
    url = os.environ.get("DATABASE_URL", "postgresql+psycopg2://USUARIO:SENHA@HOST:5432/BANCO")
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text(SQL))
        cols = list(result.keys())
        rows = result.fetchall()
    print(cols)
    for row in rows[:50]:
        print(dict(zip(cols, row)))
    print(f"\\n{len(rows)} linha(s).")


if __name__ == "__main__":
    main()
'''

_PYSPARK_TPL = '''# Gerado pelo TDIA-CodeGen — PySpark (leitura via JDBC)
# Requer o driver JDBC do PostgreSQL no classpath do Spark, ex.:
#   spark-submit --packages org.postgresql:postgresql:42.7.3 este_script.py
import os
from pyspark.sql import SparkSession

SQL = """___SQL___"""


def main():
    spark = SparkSession.builder.appName("tdia-codegen").getOrCreate()
    df = (
        spark.read.format("jdbc")
        .option("url", os.environ.get("JDBC_URL", "jdbc:postgresql://HOST:5432/BANCO"))
        .option("query", SQL)
        .option("user", os.environ.get("DB_USER", "USUARIO"))
        .option("password", os.environ.get("DB_PASSWORD", "SENHA"))
        .option("driver", "org.postgresql.Driver")
        .load()
    )
    df.show(50, truncate=False)
    print(f"{df.count()} linha(s).")
    return df


if __name__ == "__main__":
    main()
'''

_PYCODE_TEMPLATES = {"pandas": _PANDAS_TPL, "sqlalchemy": _SQLALCHEMY_TPL, "pyspark": _PYSPARK_TPL}


def _embed_sql(sql: str) -> str:
    """Escapa o SQL para embutir com segurança numa string tripla Python."""
    return sql.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')


def generate_pycode(sql: str, lib: str) -> str:
    """Gera um script Python (pandas / sqlalchemy / pyspark) que executa o SQL."""
    tpl = _PYCODE_TEMPLATES.get((lib or "pandas").lower(), _PANDAS_TPL)
    clean = (sql or "").strip().rstrip(";").strip()
    return tpl.replace("___SQL___", _embed_sql(clean))
