# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# Fale com Seus Dados — production image
#
# Single-stage build on top of python:3.11-slim. Copies the app, installs
# Python deps, and runs uvicorn directly (NOT run.py — that uses reload=True
# which is for local dev only). Designed to be paired with the docker-compose
# stack in this repo (which adds Postgres and persistent volumes).
# ---------------------------------------------------------------------------

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    WEB_CONCURRENCY=2

# System packages required by:
#   psycopg[binary]  → libpq runtime
#   pandas/openpyxl  → no native deps but build-essential helps optional wheels
#   curl             → used by HEALTHCHECK and operator debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq5 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (separate layer for build-cache reuse on
# code changes that don't touch requirements.txt).
COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# TDIA-CodeGen: parser SQL para o autorizador por-statement. Em camada própria,
# após o requirements.txt, para NÃO invalidar o cache pesado das deps acima.
RUN pip install "sqlglot>=25,<31"

# Copy the rest of the source after deps so a code-only change does not bust
# the requirements layer.
COPY . .

# Run as a non-root user. uploads/ and data/ are writable so the volumes
# mounted by docker-compose can be owned by this user.
RUN useradd -m -u 1000 appuser \
    && mkdir -p /app/uploads /app/data \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Healthcheck hits a route that does not require auth. /api/auth/check
# returns 200 with a JSON body whether or not a session cookie is present.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/api/auth/check" >/dev/null || exit 1

# WEB_CONCURRENCY can be overridden by docker-compose / the runtime env.
# uvicorn directly, no reload. Workers >1 require Postgres (already required).
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${HOST} --port ${PORT} --workers ${WEB_CONCURRENCY} --proxy-headers --forwarded-allow-ips='*'"]
