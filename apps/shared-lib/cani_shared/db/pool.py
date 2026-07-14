"""Single shared Postgres connection pool per process."""

from __future__ import annotations

from functools import lru_cache

from psycopg_pool import ConnectionPool


@lru_cache
def get_pool(dsn: str) -> ConnectionPool:
    return ConnectionPool(conninfo=dsn, min_size=1, max_size=10, open=True)
