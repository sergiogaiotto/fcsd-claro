#!/usr/bin/env bash
# Importa um CSV (do seu PC) para o banco do app fcsd como uma tabela,
# associando a uma Tabela Diamante (Diamond Layer) e/ou DataMart.
# Copia o CSV para o container, roda o importador Python e limpa o temporario.
#
# Uso:
#   ./scripts/import_csv.sh <csv> [--diamond-layer NOME] [--datamart NOME] \
#       [--table NOME] [--mode replace|append] [--sep auto|';'|','] [--encoding utf-8] [--owner-login LOGIN]
#
# Exemplos:
#   ./scripts/import_csv.sh ./pagamentos.csv --diamond-layer Financeiro
#   ./scripts/import_csv.sh ./dados.csv --datamart default --mode replace
set -euo pipefail

CONTAINER="${CONTAINER:-fcsd-app}"
CSV="${1:-}"
[ -n "$CSV" ] && shift || true

if [ -z "$CSV" ]; then
  echo "Uso: import_csv.sh <csv> [--diamond-layer NOME] [--datamart NOME] [--table NOME] [--mode replace|append] [--sep auto] ..." >&2
  exit 1
fi
[ -f "$CSV" ] || { echo "CSV nao encontrado: $CSV" >&2; exit 1; }

# Subdir único + nome original preservado, para o nome da tabela sair limpo
# (o script deriva o nome da tabela do nome do arquivo).
TMPDIR="/tmp/fcsd_imp_$$"
TMP="${TMPDIR}/$(basename "$CSV")"

# MSYS_NO_PATHCONV evita que o Git Bash (Windows) converta /tmp/... em caminho Windows.
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" mkdir -p "$TMPDIR"
MSYS_NO_PATHCONV=1 docker cp "$CSV" "${CONTAINER}:${TMP}"
set +e
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" python /app/scripts/import_csv.py "$TMP" "$@"
rc=$?
set -e
MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" rm -rf "$TMPDIR" >/dev/null 2>&1 || true
exit $rc
