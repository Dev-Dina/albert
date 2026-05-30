"""Lead lifecycle tests (feature 007, US2).

Covers the pure transition map, the GET/PATCH endpoints (allowed → 200 +
status_changed_at; disallowed → 409 unchanged; unknown value → 422), and
cross-tenant isolation (Beta cannot view/patch an Acme lead → 404).

Uses a shared StaticPool in-memory SQLite engine (mirrors
test_admin_leads_endpoint). Each scenario uses its own seeded lead id so the
tests do not interfere.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.db.base import Base
from app.db.models.lead import Lead
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app
from app.services import lead_lifecycle as lc

client = TestClient(app)


# --- T021: pure transition map ---------------------------------------------


def test_allowed_transitions() -> None:
    assert lc.can_transition("new", "contacted")
    assert lc.can_transition("new", "lost")
    assert lc.can_transition("contacted", "qualified")
    assert lc.can_transition("contacted", "lost")
    assert lc.can_transition("qualified", "won")
    assert lc.can_transition("qualified", "lost")


def test_disallowed_and_terminal_transitions() -> None:
    # backward / skipping
    assert not lc.can_transition("contacted", "new")
    assert not lc.can_transition("qualified", "contacted")
    assert not lc.can_transition("new", "won")
    assert not lc.can_transition("new", "qualified")
    # terminal states have no outgoing transitions
    assert lc.allowed_targets("won") == set()
    assert lc.allowed_targets("lost") == set()
    assert not lc.can_transition("won", "lost")


def test_status_validity() -> None:
    assert lc.is_valid_status("new")
    assert not lc.is_valid_status("frozen")
    assert lc.LEAD_STATUSES == ("new", "contacted", "qualified", "won", "lost")


# --- T022 / T023: endpoint integration -------------------------------------

_TABLES = ("users", "tenants", "tenant_memberships", "leads")
_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
_SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ADMIN_A = uuid.uuid4()
ADMIN_B = uuid.uuid4()

LEAD_ALLOW = uuid.uuid4()
LEAD_DISALLOW = uuid.uuid4()
LEAD_UNKNOWN = uuid.uuid4()
LEAD_CROSS = uuid.uuid4()

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    for lid in (LEAD_ALLOW, LEAD_DISALLOW, LEAD_UNKNOWN, LEAD_CROSS):
        session.add(
            Lead(id=lid, tenant_id=TENANT_A, name="A lead",
                 contact="a@x.test", intent="demo", status="new")
        )
    await session.commit()
    _state["ready"] = True


async def _override_get_db():
    async with _SessionLocal() as session:
        await _ensure_seeded(session)
        yield session


def _as(tenant_id: uuid.UUID, user_id: uuid.UUID) -> None:
    app.dependency_overrides[require_admin_identity] = lambda: AdminIdentity(
        user_id=user_id, tenant_id=tenant_id
    )


def setup_function() -> None:
    app.dependency_overrides[get_db] = _override_get_db


def teardown_function() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(require_admin_identity, None)


def test_get_lead_returns_detail() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.get(f"/api/v1/admin/leads/{LEAD_ALLOW}")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "new"
    assert r.json()["status_changed_at"] is None


def test_allowed_transition_persists_and_stamps_time() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.patch(f"/api/v1/admin/leads/{LEAD_ALLOW}", json={"status": "contacted"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "contacted"
    assert body["status_changed_at"] is not None
    # persisted
    again = client.get(f"/api/v1/admin/leads/{LEAD_ALLOW}")
    assert again.json()["status"] == "contacted"


def test_disallowed_transition_returns_409_unchanged() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.patch(f"/api/v1/admin/leads/{LEAD_DISALLOW}", json={"status": "won"})
    assert r.status_code == 409, r.text
    # unchanged
    assert client.get(f"/api/v1/admin/leads/{LEAD_DISALLOW}").json()["status"] == "new"


def test_unknown_status_value_returns_422() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.patch(f"/api/v1/admin/leads/{LEAD_UNKNOWN}", json={"status": "frozen"})
    assert r.status_code == 422


def test_cross_tenant_get_and_patch_are_404() -> None:
    _as(TENANT_B, ADMIN_B)
    assert client.get(f"/api/v1/admin/leads/{LEAD_CROSS}").status_code == 404
    assert client.patch(
        f"/api/v1/admin/leads/{LEAD_CROSS}", json={"status": "contacted"}
    ).status_code == 404
    # and the Acme lead remains untouched
    _as(TENANT_A, ADMIN_A)
    assert client.get(f"/api/v1/admin/leads/{LEAD_CROSS}").json()["status"] == "new"
