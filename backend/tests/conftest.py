"""Test-wide fixtures + safety stubs.

The widget session route consults Redis via ``app.core.rate_limit.check_and_consume``.
We have no Redis in unit-test CI, so the default for every test is "rate limit
is a no-op (always allowed)". Tests that exercise the dual-gate behavior
itself (test_widget_rate_limit.py) replace this stub on a per-test basis by
assigning ``route_mod.check_and_consume`` directly.
"""

from __future__ import annotations

import pytest

from app.core.rate_limit import RateLimitDecision


@pytest.fixture(autouse=True)
def _no_redis_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: every rate-limit call returns "allowed" without touching Redis."""

    async def _allow(dimension: str, key: str, capacity: int, refill_per_sec: float):
        return RateLimitDecision(
            allowed=True,
            remaining=capacity - 1,
            retry_after_seconds=0,
            dimension=dimension,
        )

    # Patch the SYMBOL imported into the route module, not the source, because
    # widget_session.py did `from app.core.rate_limit import check_and_consume`.
    monkeypatch.setattr(
        "app.api.routes.widget_session.check_and_consume", _allow, raising=False
    )
    # Also patch the source so anything else that imports it gets the no-op.
    monkeypatch.setattr("app.core.rate_limit.check_and_consume", _allow)
