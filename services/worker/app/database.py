from __future__ import annotations

import atexit
import os
from contextlib import contextmanager
from threading import Lock
from typing import Iterator

from psycopg2.extensions import connection as PgConnection
from psycopg2.pool import ThreadedConnectionPool

_pools: dict[str, ThreadedConnectionPool] = {}
_pool_lock = Lock()


def _pool(database_url: str) -> ThreadedConnectionPool:
    existing = _pools.get(database_url)
    if existing is not None:
        return existing
    with _pool_lock:
        existing = _pools.get(database_url)
        if existing is None:
            existing = ThreadedConnectionPool(
                minconn=1,
                maxconn=int(os.getenv("STOCKBALL_DATABASE_POOL_SIZE", "10")),
                dsn=database_url,
            )
            _pools[database_url] = existing
        return existing


@contextmanager
def connection(database_url: str) -> Iterator[PgConnection]:
    pool = _pool(database_url)
    value = pool.getconn()
    try:
        yield value
        value.commit()
    except Exception:
        value.rollback()
        raise
    finally:
        pool.putconn(value)


def close_all_pools() -> None:
    with _pool_lock:
        pools = tuple(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.closeall()


atexit.register(close_all_pools)
