"""Rate-limit dual-gate tests (T050, T051, T052).

The token-exchange endpoint enforces TWO independent gates: per-IP and
per-tenant. Either gate alone can refuse with 429 + Retry-After, and one
dimension's exhaustion MUST NOT consume the other dimension's budget.

These tests monkey-patch ``app.core.rate_limit.check_and_consume`` so the
behavior of the route's wiring can be exercised without a live Redis.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitDecision
from app.main import app

client = TestClient(app)


_TENANT_ID = uuid.uuid4()
_WIDGET_ID = uuid.uuid4()
_PUBLIC_WIDGET_ID = "Acm" + "L" * 19
_ORIGIN = "http://localhost:8080"
_KEY_MATERIAL = b"dev-tenant-signing-key-bytes-32!"


def _setup_session_deps() -> None:
    """Stub DB + Vault so the route resolves the widget and gets to rate-limit."""
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, widget_repo
    from app.services import widget_session_service

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_get_by_public_id(session, public_widget_id):
        return widget_repo.PublicWidgetLookup(
            widget_id=_WIDGET_ID, tenant_id=_TENANT_ID, status="enabled"
        )

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        return True

    async def _fake_read_key(tenant_id):
        return _KEY_MATERIAL

    class _ActiveKey:
        version = 1

    async def _fake_active_key(session, tenant_id):
        return _ActiveKey()

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    widget_session_service._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _install_rate_limit(decisions: dict[tuple[str, str], RateLimitDecision]) -> dict:
    """Replace ``check_and_consume`` with a deterministic stub keyed by (dim, key).

    Returns a dict mapping (dim, key) → call count so tests can assert separation.
    """
    from app.api.routes import widget_session as route_mod

    counts: dict[tuple[str, str], int] = {}

    async def _stub(dimension: str, key: str, capacity: int, refill_per_sec: float):
        counts[(dimension, key)] = counts.get((dimension, key), 0) + 1
        decision = decisions.get((dimension, key))
        if decision is not None:
            return decision
        return RateLimitDecision(
            allowed=True, remaining=capacity - 1, retry_after_seconds=0, dimension=dimension
        )

    route_mod.check_and_consume = _stub  # type: ignore[assignment]
    return counts


def test_per_ip_rate_limit_returns_429_with_retry_after() -> None:
    """T050: per-IP exhaustion → 429 + Retry-After."""
    _setup_session_deps()
    decisions = {
        ("ip", "ip:testclient"): RateLimitDecision(
            allowed=False, remaining=0, retry_after_seconds=42, dimension="ip"
        )
    }
    _install_rate_limit(decisions)
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "42"
    # Opaque body — never name the tripped dimension to the caller (FR-015c).
    body = response.json()
    assert "ip" not in str(body).lower()
    assert "tenant" not in str(body).lower()


def test_per_tenant_rate_limit_returns_429() -> None:
    """T051: per-tenant exhaustion (independent of per-IP) → 429."""
    _setup_session_deps()
    decisions = {
        ("tenant", f"tenant:{_TENANT_ID}"): RateLimitDecision(
            allowed=False, remaining=0, retry_after_seconds=12, dimension="tenant"
        )
    }
    _install_rate_limit(decisions)
    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ORIGIN},
        json={"widget_id": _PUBLIC_WIDGET_ID},
    )
    assert response.status_code == 429
    assert response.headers.get("retry-after") == "12"


def test_per_ip_exhaustion_does_not_consume_per_tenant_budget() -> None:
    """T052: separate counters; one dimension's trip MUST NOT bill the other."""
    _setup_session_deps()
    # IP_A is rate-limited; per-tenant remains healthy. Both dimensions should
    # still be CHECKED on every call (gate is "check both, refuse either"); but
    # the per-tenant counter only increments on calls that actually pass per-IP
    # — refused-on-IP calls are not paying out tenant budget.
    decisions = {
        ("ip", "ip:testclient"): RateLimitDecision(
            allowed=False, remaining=0, retry_after_seconds=5, dimension="ip"
        ),
    }
    counts = _install_rate_limit(decisions)
    for _ in range(3):
        response = client.post(
            "/api/v1/widget/session",
            headers={"Origin": _ORIGIN},
            json={"widget_id": _PUBLIC_WIDGET_ID},
        )
        assert response.status_code == 429
    assert counts[("ip", "ip:testclient")] == 3
    # Per-tenant gate is NOT charged when per-IP refuses first.
    assert counts.get(("tenant", f"tenant:{_TENANT_ID}"), 0) == 0
