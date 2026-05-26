"""Per-tenant rate limiting backed by Redis.

Uses a sliding-window counter keyed on tenant_id so one noisy tenant cannot
starve others.  A tenant that exceeds its limit receives HTTP 429 with a
Retry-After header; all other tenants are unaffected.

Key design decisions:
- Keys are namespaced as  ``rl:{tenant_id}:{window_start_epoch}``
  so each window is independent and expired windows are auto-evicted by Redis TTL.
- Redis is used for the counter, not Postgres, to keep the hot path fast.
- If Redis is unreachable the limiter fails OPEN (logs a warning, allows the
  request).  Fail-open is the safer choice for availability; ops is alerted
  via the logged warning.  Change to fail-closed if the project requires it.

Defaults (override via settings in a future phase):
  WINDOW_SECONDS  = 60
  MAX_REQUESTS    = 60  (one per second average)
"""

from __future__ import annotations

import logging
import time
import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

WINDOW_SECONDS: int = 60
MAX_REQUESTS: int = 60


def _redis_client() -> aioredis.Redis:
    url = settings.redis_url or "redis://redis:6379/0"
    return aioredis.from_url(url, decode_responses=True)


def _window_key(tenant_id: uuid.UUID, window_start: int) -> str:
    return f"rl:{tenant_id}:{window_start}"


async def check_rate_limit(tenant_id: uuid.UUID) -> None:
    """Increment the request counter for this tenant in the current window.

    Raises HTTP 429 if the tenant has exceeded ``MAX_REQUESTS`` in the past
    ``WINDOW_SECONDS`` seconds.

    If Redis is unreachable, logs a warning and allows the request (fail-open).
    """
    now = int(time.time())
    window_start = now - (now % WINDOW_SECONDS)
    key = _window_key(tenant_id, window_start)

    try:
        client = _redis_client()
        async with client as r:
            # Pipeline makes INCR + EXPIRE atomic: if the process dies between
            # the two commands the key still gets its TTL.
            pipe = r.pipeline()
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS * 2)
            results = await pipe.execute()
            count = results[0]
            if count > MAX_REQUESTS:
                retry_after = WINDOW_SECONDS - (now % WINDOW_SECONDS)
                logger.warning(
                    "rate_limit.exceeded tenant_id=%s count=%d window=%d",
                    tenant_id,
                    count,
                    window_start,
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please retry later.",
                    headers={"Retry-After": str(retry_after)},
                )
    except HTTPException:
        raise
    except Exception:
        logger.warning(
            "rate_limit.redis_unavailable tenant_id=%s — failing open",
            tenant_id,
            exc_info=True,
        )


async def get_tenant_request_count(tenant_id: uuid.UUID) -> int:
    """Return the current request count for this tenant in the active window.

    Used for monitoring and tests.  Returns 0 if Redis is unavailable.
    """
    now = int(time.time())
    window_start = now - (now % WINDOW_SECONDS)
    key = _window_key(tenant_id, window_start)
    try:
        client = _redis_client()
        async with client as r:
            raw = await r.get(key)
            return int(raw) if raw else 0
    except Exception:
        return 0
