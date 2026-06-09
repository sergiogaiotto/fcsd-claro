#!/usr/bin/env python3
"""
Importa um CSV para o banco como uma tabela, associando a uma Diamond Layer
(Tabela Diamante) e/ou a um DataMart — 100% compatível com o app fcsd
(reusa a sanitização de nomes e as funções de associação do próprio app).

Roda DENTRO do container `fcsd-app` (que tem pandas, o driver do Postgres e
acesso ao banco via o hostname interno `db`). Use os wrappers
`scripts/import_csv.ps1` (PowerShell) ou `scripts/import_csv.sh` (Bash) para
não precisar copiar o CSV na mão.

Exemplos (dentro do container):
    python /app/scripts/import_csv.py /tmp/pagamentos.csv --diamond-layer Financeiro
    python /app/scripts/import_csv.py /tmp/dados.csv --datamart default --mode replace
    python /app/scripts/import_csv.py /tmp/x.csv --diamond-layer Vendas --table fato_vendas --sep ';'
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path

# Garante que o pacote `app` seja importável quando o script é chamado por
# caminho (python /app/scripts/import_csv.py) — a raiz do app é o diretório
# pai de scripts/.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd

from app.core.database import (
    engine,
    get_sync_connection,
    INTERNAL_TABLES,
    invalidate_tables_cache,
    get_datamart_by_name,
    create_datamart,
    assign_table_to_datamart,
    get_diamond_layer_by_name,
    create_diamond_layer,
    assign_table_to_diamond_layer,
)
from app.core.db_engine import table_exists
from app.services.excel_service import sanitize_table_name, sanitize_columns


def _read_csv(path: Path, sep: str, encoding: str) -> pd.DataFrame:
    """Lê o CSV detectando o delimitador (sep='auto') e com fallback de encoding
    utf-8 -> latin-1 (comum em CSVs brasileiros exportados do Excel)."""
    encs = [encoding]
    if encoding.lower().replace("-", "") == "utf8":
        encs.append("latin-1")
    last_err: Exception | None = None
    for enc in encs:
        try:
            if sep == "auto":
                # engine='python' + sep=None aciona o sniffer de delimitador.
                return pd.read_csv(path, sep=None, engine="python", encoding=enc)
            return pd.read_csv(path, sep=sep, encoding=enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
    raise last_err if last_err else RuntimeError("Falha ao ler CSV")


def _resolve_owner_id(login: str | None) -> int | None:
    if not login:
        return None
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT id FROM users WHERE login = ? LIMIT 1", (login,)).fetchone()
        return dict(row)["id"] if row else None
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Importa um CSV como tabela e associa a Diamond Layer (Tabela Diamante) e/ou DataMart.",
    )
    ap.add_argument("csv", help="Caminho do CSV (dentro do container)")
    ap.add_argument("--table", help="Nome base da tabela (default: nome do arquivo)")
    ap.add_argument("--diamond-layer", dest="layer", help="Tabela Diamante (cria se não existir)")
    ap.add_argument("--datamart", help="DataMart (cria se não existir)")
    ap.add_argument("--mode", choices=["replace", "append"], default="replace",
                    help="Se a tabela já existir: replace (recria) ou append (acrescenta). Default: replace")
    ap.add_argument("--sep", default="auto", help="Delimitador: auto (default), ';' ou ','")
    ap.add_argument("--encoding", default="utf-8", help="Encoding do CSV (default utf-8, fallback latin-1)")
    ap.add_argument("--owner-login", dest="owner_login",
                    help="Login do dono da tabela na Diamond Layer (default: sem dono)")
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(f"ERRO: arquivo não encontrado: {path}", file=sys.stderr)
        return 1
    if not args.layer and not args.datamart:
        print("ERRO: informe --diamond-layer e/ou --datamart (onde a tabela ficará acessível).",
              file=sys.stderr)
        return 2

    # 1) Ler CSV
    try:
        df = _read_csv(path, args.sep, args.encoding)
    except Exception as e:
        print(f"ERRO ao ler CSV: {e}", file=sys.stderr)
        return 1
    if df.empty:
        print("ERRO: CSV vazio.", file=sys.stderr)
        return 1

    # 2) Sanitizar nomes (mesma regra do upload de Excel do app)
    df.columns = sanitize_columns(df.columns)
    base = sanitize_table_name(args.table or path.stem)

    # 3) Convenção de nome: prefixo da Diamond Layer (preferida) ou do DataMart
    prefix = sanitize_table_name(args.layer or args.datamart)
    tbl = base if base.startswith(f"{prefix}_") else f"{prefix}_{base}"

    if tbl in INTERNAL_TABLES:
        print(f"ERRO: '{tbl}' colide com uma tabela interna protegida. Use outro --table.",
              file=sys.stderr)
        return 3

    # 4) Criar/escrever a tabela
    conn = get_sync_connection()
    try:
        exists = table_exists(conn, tbl)
    finally:
        conn.close()
    if_exists = args.mode if exists else "replace"
    try:
        df.to_sql(tbl, engine, if_exists=if_exists, index=False)
    except Exception as e:
        print(f"ERRO ao gravar a tabela '{tbl}': {e}", file=sys.stderr)
        return 1
    action = "append" if (exists and args.mode == "append") else ("replace" if exists else "create")

    # 5) Associar a Diamond Layer / DataMart
    assocs: list[str] = []
    if args.layer:
        layer = get_diamond_layer_by_name(args.layer) or create_diamond_layer(args.layer)
        owner_id = _resolve_owner_id(args.owner_login)
        assign_table_to_diamond_layer(layer["id"], tbl, owner_id=owner_id)
        assocs.append(f"Diamond Layer '{layer['name']}' (id={layer['id']}, owner_id={owner_id})")
    if args.datamart:
        dm = get_datamart_by_name(args.datamart) or create_datamart(args.datamart)
        assign_table_to_datamart(dm["id"], tbl)
        assocs.append(f"DataMart '{dm['name']}' (id={dm['id']})")

    invalidate_tables_cache()

    print("OK ✓")
    print(f"  Tabela : {tbl}  ({action})")
    print(f"  Linhas : {len(df)}")
    print(f"  Colunas: {', '.join(df.columns)}")
    for a in assocs:
        print(f"  → associada a {a}")
    print("  Visível no app em até ~30s (TTL do cache de tabelas); reinicie o container para imediato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
