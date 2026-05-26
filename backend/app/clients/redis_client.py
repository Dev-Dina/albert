from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.asyncio.connection import ConnectionPool

from app.core.config import settings

_DEFAULT_REDIS_URL = "redis://redis:6379/0"

_pool: ConnectionPool | None = None


def _get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.redis_url or _DEFAULT_REDIS_URL,
            decode_responses=False,
        )
    return _pool


@asynccontextmanager
async def get_redis() -> AsyncIterator[redis.Redis]:
    """Yield an async Redis client backed by a shared connection pool."""
    client = redis.Redis(connection_pool=_get_pool())
    try:
        yield client
    finally:
        await client.aclose()


async def check_redis_health() -> dict:
    """Return Redis reachability. Never raises — safe for status checks."""
    try:
        async with get_redis() as client:
            await client.ping()
    except Exception:
        return {"reachable": False}
    return {"reachable": True}
