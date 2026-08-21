from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import get_settings


@contextmanager
def get_connection():
    """One connection per call, auto-committed on clean exit.

    This is deliberately the simplest thing that works for Phase 1 — a
    pooled connection (psycopg_pool) is a straightforward swap-in here once
    request volume makes per-call connect() overhead worth avoiding.

    connect_timeout is set explicitly so an unreachable database fails in a
    few seconds instead of hanging on the OS-level TCP timeout (which is
    what happens by default, and is easy to trigger accidentally — e.g. a
    test that forgets to override the repository dependency and falls
    through to this real connection).
    """
    settings = get_settings()
    with psycopg.connect(settings.database_url, row_factory=dict_row, connect_timeout=5) as connection:
        yield connection
