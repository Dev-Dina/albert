"""Two-dimensional rate-limit primitive.

Pure Redis token-bucket via a small Lua script. Callers pass the dimension
("ip", "tenant", ...) and a key (a hashed identifier); the script is composable —
to rate-limit on both per-IP AND per-tenant, call ``check_and_consume`` twice
with separate dimensions and fail the request if either trips.

TODO: extract per-tenant bucket once Owner A's platform primitive merges.
"""

import hashlib
import hmac
import logging
import math
import time
from dataclasses import dataclass

from app.clients.redis_client import get_redis
from app.core.config import settings

logger = logging.getLogger(__name__)

# KEYS[1] = bucket key; ARGV[1] = capacity, ARGV[2] = refill_per_sec, ARGV[3] = now_ms
# Returns: {allowed (0/1), remaining (int), retry_after_seconds (int)}
_TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])

local data = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now_ms
end

local elapsed = math.max(0, now_ms - ts) / 1000.0
tokens = math.min(capacity, tokens + elapsed * refill)

local allowed = 0
local retry_after = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_after = math.ceil((1 - tokens) / refill)
end

redis.call('HMSET', key, 'tokens', tokens, 'ts', now_ms)
-- Expire idle buckets after capacity is fully refilled + a safety margin.
local ttl = math.ceil(capacity / refill) + 60
redis.call('EXPIRE', key, ttl)

return {allowed, math.floor(tokens), retry_after}
"""


@dataclass(frozen=True)
class RateLimitDecision:
    """Outcome of a single ``check_and_consume`` call."""

    allowed: bool
    remaining: int
    retry_after_seconds: int
    dimension: str


def hash_identifier(identifier: str) -> str:
    """HMAC-SHA256(identifier) for safe inclusion in log lines (FR-015c).

    Uses the JWT secret as the HMAC key. Logs never carry raw tenant ids.
    """
    mac = hmac.new(
        settings.jwt_secret.get_secret_value().encode("utf-8"),
        identifier.encode("utf-8"),
        hashlib.sha256,
    )
    return mac.hexdigest()[:16]


async def check_and_consume(
    dimension: str,
    key: str,
    capacity: int,
    refill_per_sec: float,
) -> RateLimitDecision:
    """Consume one token from a per-(dimension,key) bucket.

    Composable: callers wanting per-IP AND per-tenant gates call this twice
    with separate dimensions and combine the results.
    """
    bucket_key = f"ratelimit:{dimension}:{key}"
    now_ms = int(time.time() * 1000)
    async with get_redis() as client:
        result = await client.eval(
            _TOKEN_BUCKET_LUA,
            1,
            bucket_key,
            str(capacity),
            str(refill_per_sec),
            str(now_ms),
        )
    allowed_int, remaining, retry_after = result
    allowed = int(allowed_int) == 1
    decision = RateLimitDecision(
        allowed=allowed,
        remaining=int(remaining),
        retry_after_seconds=max(1, int(retry_after)) if not allowed else 0,
        dimension=dimension,
    )
    if not allowed:
        # FR-015c: structured log with hashed identifier; response body MUST NOT
        # disclose which dimension tripped.
        logger.warning(
            "rate_limit_trip",
            extra={
                "event": "rate_limit_trip",
                "dimension": dimension,
                "key_hash": hash_identifier(key),
                "count": capacity - decision.remaining,
                "limit": capacity,
            },
        )
    return decision


def per_minute_to_refill(per_minute: int) -> float:
    """Convert a per-minute budget into a per-second refill rate."""
    return per_minute / 60.0


def capacity_from_per_minute(per_minute: int) -> int:
    """Bucket capacity == burst budget; use the per-minute value as the cap."""
    return max(1, math.floor(per_minute))
