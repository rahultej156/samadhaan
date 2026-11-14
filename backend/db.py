"""
Database access.

Measured against our Supabase project (ap-southeast-1, from Hyderabad):

    cold connect : 2906 ms
    first query  :  359 ms
    warm query   :   90 ms

A tool call has to answer inside 2 seconds, so opening a connection per request
would spend the whole budget on the TLS handshake. The pool is not an
optimisation here; it is the difference between working and not working.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config

log = logging.getLogger("samadhan.db")

_pool: ConnectionPool | None = None


def open_pool() -> None:
    """Called once at startup. Pre-warms connections so the first real tool
    call does not pay the 2.9 s handshake."""
    global _pool
    if _pool is not None:
        return
    if not config.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is empty; fill in backend/.env")

    _pool = ConnectionPool(
        conninfo=config.DATABASE_URL,
        min_size=2,
        max_size=8,
        timeout=10,
        max_lifetime=1800,
        # prepare_threshold=None disables psycopg's automatic prepared
        # statements. Measured against this project, 40 mixed queries through
        # Supabase's Supavisor pooler:
        #     prepared ON  : p50 57-106 ms, total 3005-5134 ms
        #     prepared OFF : p50  51-56 ms, total 2720-2760 ms
        # Supavisor does not handle PREPARE well, and our tools issue many
        # distinct statements rather than the same one repeatedly, so we pay
        # the prepare cost without ever getting the reuse benefit.
        kwargs={"row_factory": dict_row, "autocommit": False,
                "prepare_threshold": None},
        open=False,
        name="samadhan",
    )
    _pool.open(wait=True, timeout=30)
    log.info("db pool open (min 2, max 8)")


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx() -> Iterator[Any]:
    """
    A cursor inside a transaction. Commits on success, rolls back on error.

    Every tool handler runs in exactly one of these: the action, its audit row
    and its idempotency record either all land or none do. A pickup booked
    without an audit row would be a pickup nobody can explain.
    """
    if _pool is None:
        raise RuntimeError("db pool is not open")
    with _pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur


def healthcheck() -> dict[str, Any]:
    with tx() as cur:
        cur.execute("select now() as at, current_database() as db")
        row = cur.fetchone()
    stats = _pool.get_stats() if _pool else {}
    return {
        "db": row["db"],
        "at": row["at"].isoformat(),
        "pool_size": stats.get("pool_size"),
        "pool_available": stats.get("pool_available"),
    }
