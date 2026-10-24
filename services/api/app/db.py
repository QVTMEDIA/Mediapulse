from contextlib import contextmanager
from typing import Optional

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

# Pooled instead of one psycopg.connect() per call (the original, simpler
# Phase-1 design — see git history) — found live to be the dominant cost of
# every single request once other N+1-connection bugs elsewhere were fixed:
# even one already-efficient query still took ~5-6s in production purely
# from opening a fresh TCP+TLS+Postgres-auth handshake every time, on every
# screen, on every navigation. A handful of long-lived pooled connections
# gets reused across requests instead.
#
# Built lazily — the pool object is only constructed (and its first real
# connection opened) on the first actual get_connection() call, not at
# import time. Constructing a psycopg_pool.ConnectionPool doesn't block or
# raise even if the database is unreachable (it opens connections on
# background worker threads), so this distinction isn't about avoiding an
# import-time crash — it's about never touching a real database at all
# during `import app.main`, which the whole test suite (API_REPOSITORY=
# memory) and CI depend on being safe with no Postgres running.
#
# min_size/max_size are deliberately modest: this app runs as a single
# small instance (Render free tier), and the database itself is reached
# through Supabase's own Session pooler, which has its own modest
# connection ceiling — a large local pool would just move the bottleneck
# to Supabase's pooler instead of removing it.
_pool: Optional[ConnectionPool] = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=5,
            kwargs={'row_factory': dict_row, 'connect_timeout': 5},
            # How long a caller waits to acquire a pooled connection before
            # giving up — plays the same "fail fast, don't hang" role the
            # old per-call connect_timeout did (a test that forgets to
            # override a repository dependency and falls through to this
            # real connection now waits at most this long, not indefinitely).
            timeout=10,
        )
    return _pool


@contextmanager
def get_connection():
    """A connection from the shared pool, auto-committed on clean exit --
    ConnectionPool.connection() wraps the yielded connection in its own
    normal context-manager behavior (commit on success, rollback on error),
    identical to what `with psycopg.connect(...) as connection:` did here
    before; only where the connection comes from changed."""
    with _get_pool().connection() as connection:
        yield connection


# Comfortably under Postgres's 65535-parameter-per-statement limit for the
# widest caller so far (uploads.py's media_activity insert, 14 columns):
# 1000 rows x 14 = 14,000 params. Not tuned per-caller -- the point is
# "many fewer round trips than one per row", not squeezing the exact max.
_BULK_INSERT_BATCH_SIZE = 1000


def insert_rows_batched(
    conn, table: str, columns: list, rows: list, batch_size: int = _BULK_INSERT_BATCH_SIZE, on_batch=None
):
    """Bulk-inserts `rows` (each a tuple positionally matching `columns`)
    into `table` using multi-row `INSERT ... VALUES (...), (...), ...`
    statements instead of executemany()'s one-round-trip-per-row behavior.

    Found live: a 17,136-row ratings upload's per-row executemany() insert
    hung the backend process long enough (tens of seconds of nothing but
    network round trips to Supabase, one per row) that Render's own health
    check stopped getting a response and force-restarted the container mid-
    request -- which looked like a CORS failure in the browser (the
    connection was dropped, not refused) but was really the whole API
    frozen for every user, not just this one upload. Batching cuts N round
    trips down to ceil(N / batch_size), typically a couple dozen for a file
    this size instead of thousands. See CHANGELOG.md.

    on_batch, if given, is called with the number of rows just inserted
    after each batch completes -- real, already-committed-to-this-
    statement progress for a caller tracking an upload job's total/
    processed (see app/upload_jobs.py), not a simulated/interpolated
    fraction."""
    if not rows:
        return
    columns_sql = ', '.join(columns)
    placeholder_row = '(' + ', '.join(['%s'] * len(columns)) + ')'
    with conn.cursor() as cur:
        for start in range(0, len(rows), batch_size):
            chunk = rows[start:start + batch_size]
            values_sql = ', '.join([placeholder_row] * len(chunk))
            params = [value for row in chunk for value in row]
            cur.execute(f'INSERT INTO {table} ({columns_sql}) VALUES {values_sql}', params)
            if on_batch:
                on_batch(len(chunk))
