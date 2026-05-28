import json
import logging

from redis.asyncio import Redis

from app.core.config import settings
from app.core.redaction import redact

logger = logging.getLogger(__name__)

_MAX_TURNS = 10


def _redact(text: str) -> str:
    return redact(text).text


async def load_history(redis: Redis, tenant_id: str, conversation_id: str) -> list[dict]:
    """Return up to _MAX_TURNS prior turns for this conversation. Returns [] on any error."""
    key = f"conv:{tenant_id}:{conversation_id}"
    try:
        raw = await redis.get(key)
        if not raw:
            return []
        turns: list[dict] = json.loads(raw)
        return turns[-_MAX_TURNS:]
    except Exception:
        logger.warning("memory.load_history failed tenant=%s conv=%s", tenant_id, conversation_id)
        return []


async def save_turn(
    redis: Redis,
    tenant_id: str,
    conversation_id: str,
    user_message: str,
    assistant_reply: str,
) -> None:
    """Append a turn, trim to _MAX_TURNS, and reset the TTL. Silently skips on error."""
    key = f"conv:{tenant_id}:{conversation_id}"
    try:
        raw = await redis.get(key)
        turns: list[dict] = json.loads(raw) if raw else []
        turns.append({"role": "user", "content": _redact(user_message)})
        turns.append({"role": "assistant", "content": assistant_reply})
        turns = turns[-_MAX_TURNS:]
        await redis.setex(key, settings.redis_session_ttl, json.dumps(turns))
    except Exception:
        logger.warning("memory.save_turn failed tenant=%s conv=%s", tenant_id, conversation_id)
