#!/usr/bin/env python3
"""
Importa um CSV para o banco como uma tabela, associando a uma Diamond Layer
(Tabela Diamante) e/ou a um DataMart — 100% compatível com o app fcsd
(reusa a sanitização de nomes e as funções de associação do próprio app).

Suporta arquivos GRANDES: acima de ~80 MB (ou com --chunksize) usa um loader
em STREAMING — lê o CSV em blocos, infere os tipos a partir de uma amostra e
coage com segurança (valores inválidos viram NULL) — mantendo baixo uso de
memória para não derrubar o app.

Roda DENTRO do container `fcsd-app`. Use os wrappers import_csv.{cmd,ps1,sh}.

Exemplos (dentro do container):
    python /app/scripts/import_csv.py /tmp/base.csv --diamond-layer Financeiro
    python /app/scripts/import_csv.py /tmp/base.csv --datamart default --mode replace
"""
from __future__ import annotations
import argparse
import csv as _csv
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

# Acima deste tamanho, usa o loader em streaming (baixa memória).
_STREAM_THRESHOLD_BYTES = 80 * 1024 * 1024  # 80 MB
_SAMPLE_ROWS = 300_000                      # amostra para inferir tipos
_DEFAULT_CHUNKSIZE = 200_000                # linhas por bloco no streaming


def _detect_encoding(path: Path, preferred: str) -> str:
    """Tenta o encoding informado; se falhar a decodificação, cai para latin-1."""
    for enc in [preferred, "latin-1"]:
        try:
            with open(path, "r", encoding=enc, newline="") as f:
                f.read(64 * 1024)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def _detect_sep(path: Path, encoding: str, sep: str) -> str:
    if sep and sep != "auto":
        return sep
    with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
        head = f.read(64 * 1024)
    try:
        return _csv.Sniffer().sniff(head, delimiters=";,|\t").delimiter
    except Exception:
        return ","


def _infer_target_types(sample: pd.DataFrame) -> dict[str, str]:
    """Para cada coluna decide 'int' | 'float' | 'text' a partir da amostra."""
    types: dict[str, str] = {}
    for c in sample.columns:
        s = sample[c].dropna().astype(str).str.strip()
        s = s[s != ""]
        if s.empty:
            types[c] = "text"
            continue
        num = pd.to_numeric(s, errors="coerce")
        if num.notna().all():
            types[c] = "int" if bool((num.dropna() % 1 == 0).all()) else "float"
        else:
            types[c] = "text"
    return types


def _coerce_chunk(chunk: pd.DataFrame, types: dict[str, str]) -> pd.DataFrame:
    for c, t in types.items():
        if c not in chunk.columns:
            continue
        if t == "int":
            chunk[c] = pd.to_numeric(chunk[c], errors="coerce").astype("Int64")
        elif t == "float":
            chunk[c] = pd.to_numeric(chunk[c], errors="coerce")
        else:
            chunk[c] = chunk[c].astype("string")
    return chunk


def _resolve_owner_id(login: str | None) -> int | None:
    if not login:
        return None
    conn = get_sync_connection()
    try:
        row = conn.execute("SELECT id FROM users WHERE login = ? LIMIT 1", (login,)).fetchone()
        return dict(row)["id"] if row else None
    finally:
        conn.close()


def _load_simple(path, sep, encoding, tbl, mode) -> tuple[int, list[str]]:
    """Caminho para arquivos pequenos: carrega tudo de uma vez."""
    df = pd.read_csv(path, sep=sep, encoding=encoding)
    if df.empty:
        raise RuntimeError("CSV vazio.")
    df.columns = sanitize_columns(df.columns)
    conn = get_sync_connection()
    try:
        exists = table_exists(conn, tbl)
    finally:
        conn.close()
    if_exists = mode if exists else "replace"
    df.to_sql(tbl, engine, if_exists=if_exists, index=False)
    return len(df), list(df.columns)


def _load_streaming(path, sep, encoding, tbl, mode, chunksize) -> tuple[int, list[str]]:
    """Caminho para arquivos grandes: lê em blocos (dtype=str), infere tipos da
    amostra e coage com segurança. Baixo uso de memória."""
    sample = pd.read_csv(path, sep=sep, encoding=encoding, nrows=_SAMPLE_ROWS, dtype=str)
    if sample.empty:
        raise RuntimeError("CSV vazio.")
    cols = sanitize_columns(sample.columns)
    sample.columns = cols
    types = _infer_target_types(sample)
    del sample

    total = 0
    first = True
    reader = pd.read_csv(path, sep=sep, encoding=encoding, dtype=str, chunksize=chunksize)
    for chunk in reader:
        chunk.columns = cols
        chunk = _coerce_chunk(chunk, types)
        if first:
            if_exists = mode  # 'replace' (default) ou 'append'
            first = False
        else:
            if_exists = "append"
        # method=None (executemany do psycopg3) evita o limite de 65535 params
        # do method='multi'; chunksize interno controla o tamanho dos lotes.
        chunk.to_sql(tbl, engine, if_exists=if_exists, index=False, chunksize=10_000)
        total += len(chunk)
        print(f"  ... {total:,} linhas gravadas".replace(",", "."), flush=True)
    return total, cols


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Importa um CSV como tabela e associa a Diamond Layer (Tabela Diamante) e/ou DataMart.",
    )
    ap.add_argument("csv", help="Caminho do CSV (dentro do container)")
    ap.add_argument("--table", help="Nome base da tabela (default: nome do arquivo)")
    ap.add_argument("--diamond-layer", dest="layer", help="Tabela Diamante (cria se não existir)")
    ap.add_argument("--datamart", help="DataMart (cria se não existir)")
    ap.add_argument("--mode", choices=["replace", "append"], default="replace",
                    help="Se a tabela já existir: replace (recria) ou append. Default: replace")
    ap.add_argument("--sep", default="auto", help="Delimitador: auto (default), ';' ou ','")
    ap.add_argument("--encoding", default="utf-8", help="Encoding (default utf-8, fallback latin-1)")
    ap.add_argument("--chunksize", type=int, default=0,
                    help="Força leitura em streaming com N linhas por bloco (default: auto por tamanho)")
    ap.add_argument("--owner-login", dest="owner_login",
                    help="Login do dono da tabela na Diamond Layer (default: sem dono)")
    args = ap.parse_args()

    path = Path(args.csv)
    if not path.exists():
        print(f"ERRO: arquivo não encontrado: {path}", file=sys.stderr)
        return 1
    if not args.layer and not args.datamart:
        print("ERRO: informe --diamond-layer e/ou --datamart.", file=sys.stderr)
        return 2

    encoding = _detect_encoding(path, args.encoding)
    sep = _detect_sep(path, encoding, args.sep)
    size = path.stat().st_size

    # Nome da tabela (prefixo da camada/datamart + base sanitizada)
    base = sanitize_table_name(args.table or path.stem)
    prefix = sanitize_table_name(args.layer or args.datamart)
    tbl = base if base.startswith(f"{prefix}_") else f"{prefix}_{base}"
    if tbl in INTERNAL_TABLES:
        print(f"ERRO: '{tbl}' colide com uma tabela interna protegida. Use outro --table.", file=sys.stderr)
        return 3

    streaming = bool(args.chunksize) or size > _STREAM_THRESHOLD_BYTES
    chunksize = args.chunksize or _DEFAULT_CHUNKSIZE
    print(f"Arquivo : {path.name}  ({size / (1024*1024):.1f} MB, sep='{sep}', enc={encoding})")
    print(f"Tabela  : {tbl}  (modo {'streaming' if streaming else 'simples'})")

    try:
        if streaming:
            nrows, cols = _load_streaming(path, sep, encoding, tbl, args.mode, chunksize)
        else:
            nrows, cols = _load_simple(path, sep, encoding, tbl, args.mode)
    except Exception as e:
        print(f"ERRO ao gravar a tabela '{tbl}': {e}", file=sys.stderr)
        return 1

    # Associar a Diamond Layer / DataMart
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
    print(f"  Tabela : {tbl}")
    print(f"  Linhas : {nrows:,}".replace(",", "."))
    print(f"  Colunas: {len(cols)}")
    for a in assocs:
        print(f"  → associada a {a}")
    print("  Visível no app em até ~30s (TTL do cache) ou reinicie o container para imediato.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
