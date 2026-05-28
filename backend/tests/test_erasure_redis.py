"""Unit test for the Redis side of tenant erasure (Owner A).

Complements evals/isolation/test_erasure_total.py, which mocks ``_erase_redis``
entirely and needs a live Postgres. Here we exercise the real key-scanning
logic with a fake async Redis client (no external Redis required), asserting
that erasure purges BOTH session and conversation-memory keys for the target
tenant and leaves other tenants' keys untouched.
"""

from __future__ import annotations

import fnmatch
import uuid
from unittest.mock import patch

import pytest

from app.tenancy.erasure import _erase_redis

TENANT_X = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
TENANT_Y = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000011")


class _FakeRedis:
    """Minimal async stand-in for redis.asyncio supporting scan/delete.

    Doubles as the async context manager returned by ``from_url``.
    """

    def __init__(self, keys: list[str]) -> None:
        self._store: set[str] = set(keys)
        self.scanned_patterns: list[str] = []

    async def __aenter__(self) -> "_FakeRedis":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def scan(self, cursor: int, match: str = "*", count: int = 100):
        # Record the pattern and return every match in one pass (cursor -> 0).
        self.scanned_patterns.append(match)
        matched = [k for k in self._store if fnmatch.fnmatch(k, match)]
        return 0, matched

    async def delete(self, *keys: str) -> int:
        removed = 0
        for key in keys:
            if key in self._store:
                self._store.discard(key)
                removed += 1
        return removed


@pytest.mark.asyncio
async def test_erase_redis_purges_session_and_conversation_keys() -> None:
    fake = _FakeRedis(
        [
            f"session:{TENANT_X}:s1",
            f"conv:{TENANT_X}:c1",
            f"conv:{TENANT_X}:c2",
            # Other tenant + unrelated keys MUST survive.
            f"session:{TENANT_Y}:s1",
            f"conv:{TENANT_Y}:c1",
            "unrelated:key",
        ]
    )

    with patch("app.tenancy.erasure.aioredis.from_url", return_value=fake):
        count = await _erase_redis(TENANT_X)

    # Target tenant's session AND conversation keys are gone.
    assert f"session:{TENANT_X}:s1" not in fake._store
    assert f"conv:{TENANT_X}:c1" not in fake._store
    assert f"conv:{TENANT_X}:c2" not in fake._store
    assert count == 3

    # Isolation: other tenant + unrelated keys untouched.
    assert f"session:{TENANT_Y}:s1" in fake._store
    assert f"conv:{TENANT_Y}:c1" in fake._store
    assert "unrelated:key" in fake._store

    # Both prefixes were scanned.
    assert any(p.startswith("session:") for p in fake.scanned_patterns)
    assert any(p.startswith("conv:") for p in fake.scanned_patterns)


@pytest.mark.asyncio
async def test_erase_redis_swallows_connection_errors() -> None:
    # Erasure of external stores must not raise — Postgres erasure already
    # committed; a Redis outage is logged, not fatal.
    with patch(
        "app.tenancy.erasure.aioredis.from_url", side_effect=ConnectionError("down")
    ):
        count = await _erase_redis(TENANT_X)
    assert count == 0
