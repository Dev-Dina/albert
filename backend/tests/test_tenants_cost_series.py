"""Contract tests for GET /tenants/cost/series (FR-050 exception 4).

Covers: happy path (one zero-filled daily series per tenant), header
consistency (each tenant's summed bucket cost == that tenant's /cost/all
scalar total for the same window), admin → 403, and the content-exclusion
guard (response JSON keys ⊆ the cost-series allowlist).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.auth.models import Role
from app.auth.roles import CurrentUser, get_current_user
from app.db.base import Base
from app.db.models.cost_event import CostEvent
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app

client = TestClient(app)

_TABLES = ("tenants", "cost_events")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

MANAGER_ID = uuid.uuid4()
TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()

# Window: 2026-05-01 .. 2026-05-05 inclusive (5 daily buckets).
_SINCE = datetime(2026, 5, 1, 0, 0, 0)
_UNTIL = datetime(2026, 5, 5, 23, 59, 59)

_TOP_ALLOWLIST = {"tenant_id", "buckets"}
_BUCKET_ALLOWLIST = {"date", "cost_usd", "total_tokens"}

_state = {"ready": False}


def _event(tenant_id: uuid.UUID, when: datetime, cost: str, inp: int, out: int) -> CostEvent:
    return CostEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        call_type="llm",
        model="gemini-test",
        input_tokens=inp,
        output_tokens=out,
        cost_usd=Decimal(cost),
        created_at=when,
    )


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    # Tenant A: two events on 05-01, one on 05-02. Tenant B: one on 05-03.
    session.add(_event(TENANT_A, datetime(2026, 5, 1, 9, 0), "1.50", 100, 20))
    session.add(_event(TENANT_A, datetime(2026, 5, 1, 15, 0), "0.50", 40, 10))
    session.add(_event(TENANT_A, datetime(2026, 5, 2, 11, 0), "2.00", 200, 50))
    session.add(_event(TENANT_B, datetime(2026, 5, 3, 8, 0), "0.75", 60, 15))
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _headers(role: Role, tenant_id: uuid.UUID | None = None) -> dict[str, str]:
    # 003 resolves role/tenant server-side, so override the resolved identity
    # dependency instead of minting a JWT.
    user_id = MANAGER_ID if role == Role.tenant_manager else uuid.uuid4()
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=user_id, role=role, tenant_id=tenant_id, email="user@test.local"
    )
    return {}


def _window_query() -> str:
    return f"since={_SINCE.isoformat()}&until={_UNTIL.isoformat()}"


def setup_function() -> None:
    app.dependency_overrides[get_db] = _override_get_db


def teardown_function() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_current_user, None)


def test_happy_path_one_zero_filled_series_per_tenant() -> None:
    response = client.get(
        f"/tenants/cost/series?{_window_query()}",
        headers=_headers(Role.tenant_manager),
    )
    assert response.status_code == 200
    series = response.json()
    # One series per tenant that has events.
    assert {row["tenant_id"] for row in series} == {str(TENANT_A), str(TENANT_B)}
    for row in series:
        # 5 inclusive daily buckets, zero-filled where there are no events.
        assert len(row["buckets"]) == 5
        dates = [bucket["date"] for bucket in row["buckets"]]
        assert dates == [
            "2026-05-01",
            "2026-05-02",
            "2026-05-03",
            "2026-05-04",
            "2026-05-05",
        ]


def test_bucket_sum_matches_cost_all_scalar_total() -> None:
    series = client.get(
        f"/tenants/cost/series?{_window_query()}",
        headers=_headers(Role.tenant_manager),
    ).json()
    cost_all = client.get(
        f"/tenants/cost/all?{_window_query()}",
        headers=_headers(Role.tenant_manager),
    ).json()

    scalar_by_tenant = {row["tenant_id"]: Decimal(row["total_cost_usd"]) for row in cost_all}
    for row in series:
        bucket_sum = sum((Decimal(bucket["cost_usd"]) for bucket in row["buckets"]), Decimal("0"))
        assert bucket_sum == scalar_by_tenant[row["tenant_id"]]

    # Sanity: tenant A summed across buckets is 1.50 + 0.50 + 2.00 = 4.00.
    a_row = next(row for row in series if row["tenant_id"] == str(TENANT_A))
    assert sum((Decimal(b["cost_usd"]) for b in a_row["buckets"]), Decimal("0")) == Decimal("4.00")


def test_admin_role_gets_403() -> None:
    response = client.get(
        f"/tenants/cost/series?{_window_query()}",
        headers=_headers(Role.tenant_admin, tenant_id=TENANT_A),
    )
    assert response.status_code == 403


def test_response_excludes_tenant_content() -> None:
    series = client.get(
        f"/tenants/cost/series?{_window_query()}",
        headers=_headers(Role.tenant_manager),
    ).json()
    assert series
    for row in series:
        assert set(row.keys()) <= _TOP_ALLOWLIST
        for bucket in row["buckets"]:
            assert set(bucket.keys()) <= _BUCKET_ALLOWLIST
