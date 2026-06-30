"""PostgreSQL database connection layer.

The single entry point for opening a connection to the configured Postgres
database. The wrapper translates ``?`` placeholders to ``%s`` so historical
call sites (originally written for sqlite3) keep working unchanged.

Why a wrapper?
- Many existing call sites use ``?`` as the parameter placeholder. psycopg
  uses ``%s``. We translate transparently so they do not need rewrites.
- We expose a uniform row-as-mapping access via psycopg's ``dict_row``
  factory so code that did ``row["column"]`` keeps working.
- We provide ``cursor`` and ``execute`` shortcuts that mirror the subset
  of the DB-API used across the app.

This wrapper is intentionally thin — it is not a full ORM. It supports the
operations actually used today and nothing more.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Iterable, Sequence

from app.core.config import settings


class HybridRow(Mapping):
    """Row with sqlite3.Row-style hybrid access.

    Supports:
      - positional access: ``row[0]``
      - mapping access:    ``row["column_name"]``
      - mapping iteration: ``dict(row)``, ``list(row.keys())``, ``row.items()``

    psycopg's built-in row factories are either tuple-only or dict-only, but
    the existing codebase uses both styles. This hybrid factory keeps the
    SQLite-era call sites working without rewrites.
    """

    __slots__ = ("_cols", "_values", "_index")

    def __init__(self, cols: tuple, values: tuple):
        self._cols = cols
        self._values = values
        self._index = {c: i for i, c in enumerate(cols)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        try:
            return self._values[self._index[key]]
        except KeyError:
            raise KeyError(key)

    def __iter__(self):
        return iter(self._cols)

    def __len__(self):
        return len(self._cols)

    def keys(self):
        return list(self._cols)

    def values(self):
        return list(self._values)

    def items(self):
        return list(zip(self._cols, self._values))

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def __repr__(self) -> str:
        return f"HybridRow({dict(zip(self._cols, self._values))!r})"


def _hybrid_row_factory(cursor):
    """psycopg row factory that yields HybridRow instances."""
    cols = tuple(d[0] for d in (cursor.description or []))
    def _make(values):
        return HybridRow(cols, tuple(values))
    return _make


# Psycopg is imported lazily so that running the test suite or import-only
# checks does not hard-require the driver in environments that never open a
# real connection. The first connect() call resolves it.
_PSYCOPG = None


def _load_psycopg():
    global _PSYCOPG
    if _PSYCOPG is None:
        import psycopg  # type: ignore
        _PSYCOPG = (psycopg,)
    return _PSYCOPG


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------
# Without a pool, every get_sync_connection() call opens a fresh TCP+TLS+auth
# handshake to Postgres. On a request-heavy endpoint that can mean dozens of
# round-trips per page load. We use psycopg_pool's ConnectionPool to amortise.
#
# Tuning rationale (Render free/starter, single web instance):
#   - min_size=1   keep one warm idle connection so the first request is fast
#   - max_size=10  Render Postgres allows ~100 connections; 10 leaves headroom
#                  for the SQLAlchemy engine's own pool and any psql sidecars
#   - max_idle=600 close idle connections after 10 min so the server doesn't
#                  GC them on us (managed Postgres often disconnects after 30 min)
#   - timeout=30   block at most 30s waiting for a free connection before
#                  raising; keeps slow requests from cascading into hangs
#   - kwargs include application_name so the connections show up labelled
#     in pg_stat_activity (much easier to debug)

_POOL = None


def _build_pool_url() -> str:
    """Pop the +psycopg suffix and append application_name for observability."""
    url = settings.database_url
    if url.startswith("postgresql+"):
        url = "postgresql://" + url.split("://", 1)[1]
    sep = "&" if "?" in url else "?"
    if "application_name=" not in url:
        url = f"{url}{sep}application_name=fale-com-seus-dados"
    if "connect_timeout=" not in url:
        url = f"{url}&connect_timeout={settings.db_connect_timeout_seconds}"
    return url


def _get_pool():
    global _POOL
    if _POOL is None:
        from psycopg_pool import ConnectionPool  # type: ignore
        # min_size=0 + open=False — the pool is created without trying to
        # establish any connection upfront. The first getconn() call opens
        # one on demand. This keeps app boot independent of DB reachability:
        # if Postgres is offline / unreachable, only requests that hit the
        # DB fail; the worker still binds to the port and Render's port
        # detector succeeds.
        _POOL = ConnectionPool(
            conninfo=_build_pool_url(),
            min_size=0,
            max_size=max(1, settings.db_pool_max_size),
            max_idle=max(30, settings.db_pool_max_idle_seconds),
            timeout=max(1, settings.db_pool_timeout_seconds),
            kwargs={
                "row_factory": _hybrid_row_factory,
                "prepare_threshold": 3,
            },
            open=False,
        )
        _POOL.open()  # idempotent; needed because open=False above
    return _POOL


def close_pool():
    """Drain and close the pool (called on app shutdown). Safe to call when
    no pool was ever created."""
    global _POOL
    if _POOL is not None:
        try:
            _POOL.close()
        except Exception:
            pass
        _POOL = None


_QMARK_RE = re.compile(r"\?")


def _translate_sql(sql: str) -> str:
    """Translate sqlite-style ``?`` placeholders to psycopg-style ``%s``."""
    if "?" in sql:
        return _QMARK_RE.sub("%s", sql)
    return sql


class DialectCursor:
    """Cursor wrapper that translates ? -> %s and exposes the subset of the
    DB-API used across the codebase (execute / fetchone / fetchall /
    fetchmany / rowcount).

    Note: psycopg has no ``lastrowid``; the property is kept and returns
    ``None``. Code that needs the inserted id should ``RETURNING id``.
    """

    def __init__(self, cur):
        self._cur = cur

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> "DialectCursor":
        sql = _translate_sql(sql)
        if params is None:
            self._cur.execute(sql)
        else:
            self._cur.execute(sql, params)
        return self

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> "DialectCursor":
        self._cur.executemany(_translate_sql(sql), seq)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size: int | None = None):
        if size is None:
            return self._cur.fetchmany()
        return self._cur.fetchmany(size)

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return None  # Postgres has no lastrowid; use RETURNING

    @property
    def description(self):
        return self._cur.description

    def close(self):
        self._cur.close()


class DialectConnection:
    """Thin connection wrapper around a psycopg connection borrowed from the
    pool. ``close()`` returns the underlying connection to the pool instead
    of physically closing it, so it can be reused by the next request.
    Exposes ``execute``, ``executemany``, ``cursor``, ``commit``,
    ``rollback``, ``close``, plus context-manager support.
    """

    def __init__(self, raw, pool=None):
        self._raw = raw
        self._pool = pool  # None when not pool-managed (rare)
        self._returned = False

    @property
    def dialect(self) -> str:
        return "postgres"

    @property
    def raw(self):
        return self._raw

    def cursor(self) -> DialectCursor:
        return DialectCursor(self._raw.cursor())

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> DialectCursor:
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executemany(self, sql: str, seq: Iterable[Sequence[Any]]) -> DialectCursor:
        cur = self.cursor()
        cur.executemany(sql, seq)
        return cur

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        """Return to pool (or hard-close when not pooled). Idempotent."""
        if self._returned:
            return
        self._returned = True
        if self._pool is not None:
            # Return the connection to the pool in a clean (IDLE) state.
            # Read-only call sites never commit, so psycopg leaves the
            # implicit SELECT transaction open (INTRANS); without this the
            # pool would roll it back on return and log a WARNING for every
            # read. Roll back here so the connection goes back IDLE silently.
            # Write paths already commit() before close(), so this is a
            # harmless no-op there (it can only discard an uncommitted
            # residue, never committed work).
            try:
                self._raw.rollback()
            except Exception:
                pass
            # putconn returns a healthy conn to the pool; broken conns are
            # discarded automatically by psycopg_pool.
            try:
                self._pool.putconn(self._raw)
            except Exception:
                try:
                    self._raw.close()
                except Exception:
                    pass
        else:
            self._raw.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            try:
                self.commit()
            except Exception:
                pass
        else:
            try:
                self.rollback()
            except Exception:
                pass
        self.close()
        return False


def connect() -> DialectConnection:
    """Borrow a connection from the pool (lazily created on first call).

    Returns a ``DialectConnection`` whose ``execute()`` / ``cursor()`` calls
    accept ``?``-style placeholders (translated to ``%s``) and yield
    HybridRow instances (positional + mapping access, parity with sqlite3.Row).
    Calling ``.close()`` (or exiting the context manager) returns the
    underlying connection to the pool — it is NOT physically closed.
    """
    pool = _get_pool()
    raw = pool.getconn()
    # Apply per-session timeouts via set_config(). Postgres does NOT accept
    # bind parameters in plain ``SET`` commands (`SET statement_timeout = $1`
    # is a syntax error). The set_config() function does accept parameters,
    # which lets us avoid building SQL by string interpolation.
    stmt_ms = max(1000, int(settings.db_statement_timeout_ms))
    lock_ms = max(1000, int(settings.db_lock_timeout_ms))
    with raw.cursor() as _c:
        _c.execute(
            "SELECT set_config('statement_timeout', %s, false), "
            "       set_config('lock_timeout', %s, false)",
            (f"{stmt_ms}ms", f"{lock_ms}ms"),
        )
    # The pool sets row_factory via `kwargs={"row_factory": ...}` at
    # connection-creation time; reapply on each borrow defensively in case
    # somebody changed it on the previous request.
    raw.row_factory = _hybrid_row_factory
    return DialectConnection(raw, pool=pool)


def column_exists(conn: DialectConnection, table: str, column: str, schema: str = "public") -> bool:
    """Check whether a column exists. Replaces the SQLite ``try / except
    OperationalError`` pattern used for incremental ALTER TABLE migrations.
    """
    cur = conn.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? AND column_name = ? LIMIT 1",
        (schema, table, column),
    )
    return cur.fetchone() is not None


def table_exists(conn: DialectConnection, table: str, schema: str = "public") -> bool:
    cur = conn.execute(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ? LIMIT 1",
        (schema, table),
    )
    return cur.fetchone() is not None
