import json

import asyncpg
from app.config import POSTGRES_DSN

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    # asyncpg treats jsonb as opaque text by default; decode/encode as dict
    # so callers work with plain Python dicts everywhere.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
    )


async def init_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            POSTGRES_DSN, min_size=2, max_size=10, init=_init_connection
        )
    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("DB pool not initialized — call init_pool() first")
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None
