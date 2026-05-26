import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.memory import load_history, save_turn


def _make_redis(stored: str | None = None) -> MagicMock:
    r = MagicMock()
    r.get = AsyncMock(return_value=stored)
    r.setex = AsyncMock()
    return r


@pytest.mark.asyncio
async def test_load_returns_empty_on_miss():
    redis = _make_redis(stored=None)
    result = await load_history(redis, "tenant-a", "conv-1")
    assert result == []


@pytest.mark.asyncio
async def test_save_and_load_roundtrip():
    turns = []
    redis = MagicMock()

    async def fake_get(key):
        return json.dumps(turns) if turns else None

    async def fake_setex(key, ttl, value):
        turns.clear()
        turns.extend(json.loads(value))

    redis.get = fake_get
    redis.setex = fake_setex

    await save_turn(redis, "tenant-a", "conv-1", "hello", "hi there")
    result = await load_history(redis, "tenant-a", "conv-1")
    assert len(result) == 2
    assert result[0]["role"] == "user"
    assert result[1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_max_10_turn_cap():
    # Pre-load 10 turns (5 exchanges) already stored
    existing = [{"role": "user", "content": f"msg{i}"} for i in range(10)]
    stored_value = json.dumps(existing)
    saved = []

    redis = MagicMock()
    redis.get = AsyncMock(return_value=stored_value)

    async def fake_setex(key, ttl, value):
        saved.extend(json.loads(value))

    redis.setex = fake_setex

    await save_turn(redis, "tenant-a", "conv-1", "new question", "new answer")
    # Should have trimmed to last 10
    assert len(saved) == 10


@pytest.mark.asyncio
async def test_ttl_reset_on_write():
    from app.core.config import settings

    redis = _make_redis(stored=None)
    await save_turn(redis, "tenant-a", "conv-1", "hi", "hello")
    redis.setex.assert_awaited_once()
    call_args = redis.setex.call_args
    # Second positional arg is the TTL
    assert call_args[0][1] == settings.redis_session_ttl


@pytest.mark.asyncio
async def test_cross_tenant_key_isolation():
    """Keys for different tenants must be distinct strings."""
    key_a = f"conv:tenant-a:conv-1"
    key_b = f"conv:tenant-b:conv-1"
    assert key_a != key_b

    # load_history for tenant-b should not get tenant-a's data
    tenant_a_data = json.dumps([{"role": "user", "content": "secret"}])

    async def fake_get(key):
        if key == "conv:tenant-a:conv-1":
            return tenant_a_data
        return None

    redis = MagicMock()
    redis.get = fake_get

    result = await load_history(redis, "tenant-b", "conv-1")
    assert result == []
