"""Resolve / reopen escalation tests (feature 008).

Covers the admin write path: resolve stamps status/resolved_by/resolved_at and
persists; reopen clears them; re-resolve is idempotent; an invalid value is 422;
resolving never changes the conversation's own status (decoupled); the status
filter narrows the list; and a cross-tenant PATCH is 404 with zero mutation.

Uses a shared StaticPool in-memory SQLite engine with one conversation/escalation
per scenario so the tests don't interfere (mirrors test_lead_lifecycle.py).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.db.base import Base
from app.db.models.conversation import Conversation
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app
from app.repositories import escalation_repo

client = TestClient(app)

_TABLES = ("tenants", "conversations", "escalations")
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

CONV_RESOLVE = uuid.uuid4()
CONV_DECOUPLE = uuid.uuid4()
CONV_INVALID = uuid.uuid4()
CONV_CROSS = uuid.uuid4()
CONV_REOPEN = uuid.uuid4()
CONV_FILTER_OPEN = uuid.uuid4()
CONV_FILTER_RESOLVED = uuid.uuid4()

_ALL_CONVS = (
    CONV_RESOLVE, CONV_DECOUPLE, CONV_INVALID, CONV_CROSS, CONV_REOPEN,
    CONV_FILTER_OPEN, CONV_FILTER_RESOLVED,
)

_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in _TABLES]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    for conv in _ALL_CONVS:
        session.add(
            Conversation(id=conv, tenant_id=TENANT_A, session_id=str(conv), status="escalated")
        )
    await session.flush()
    for conv in _ALL_CONVS:
        await escalation_repo.upsert(
            session, tenant_id=TENANT_A, conversation_id=conv,
            reason="needs a human", summary="ctx",
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


# --- T008: resolve stamps + persists ---------------------------------------


def test_resolve_stamps_resolver_and_persists() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.patch(f"/api/v1/admin/escalations/{CONV_RESOLVE}", json={"status": "resolved"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "resolved"
    assert body["resolved_by"] == str(ADMIN_A)
    assert body["resolved_at"] is not None
    # persisted
    again = client.get(f"/api/v1/admin/escalations/{CONV_RESOLVE}")
    assert again.json()["status"] == "resolved"
    assert again.json()["resolved_by"] == str(ADMIN_A)


# --- T009: decoupled from conversation status (FR-005) ----------------------


def test_resolve_does_not_change_conversation_status() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.patch(f"/api/v1/admin/escalations/{CONV_DECOUPLE}", json={"status": "resolved"})
    assert r.status_code == 200, r.text
    # the joined conversation status is unchanged by resolving the escalation
    assert r.json()["conversation_status"] == "escalated"
    assert client.get(
        f"/api/v1/admin/escalations/{CONV_DECOUPLE}"
    ).json()["conversation_status"] == "escalated"


# --- T010: invalid value → 422, unchanged (FR-008) --------------------------


def test_invalid_status_value_returns_422_unchanged() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.patch(f"/api/v1/admin/escalations/{CONV_INVALID}", json={"status": "bogus"})
    assert r.status_code == 422
    assert client.get(f"/api/v1/admin/escalations/{CONV_INVALID}").json()["status"] == "open"


# --- T011: cross-tenant PATCH → 404, zero mutation (FR-007) -----------------


def test_cross_tenant_patch_is_404_and_no_mutation() -> None:
    _as(TENANT_B, ADMIN_B)
    r = client.patch(f"/api/v1/admin/escalations/{CONV_CROSS}", json={"status": "resolved"})
    assert r.status_code == 404
    # Tenant A's escalation remains open / unresolved
    _as(TENANT_A, ADMIN_A)
    body = client.get(f"/api/v1/admin/escalations/{CONV_CROSS}").json()
    assert body["status"] == "open"
    assert body["resolved_by"] is None
    assert body["resolved_at"] is None


# --- T019: reopen clears + idempotent re-resolve refreshes (FR-004/FR-012) --


def test_reopen_clears_and_reresolve_is_idempotent() -> None:
    _as(TENANT_A, ADMIN_A)
    # resolve, then reopen → fields cleared
    client.patch(f"/api/v1/admin/escalations/{CONV_REOPEN}", json={"status": "resolved"})
    r = client.patch(f"/api/v1/admin/escalations/{CONV_REOPEN}", json={"status": "open"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "open"
    assert body["resolved_at"] is None
    assert body["resolved_by"] is None
    assert body["conversation_status"] == "escalated"  # reopen also decoupled
    # idempotent re-resolve: resolving twice stays resolved with resolver set
    client.patch(f"/api/v1/admin/escalations/{CONV_REOPEN}", json={"status": "resolved"})
    again = client.patch(f"/api/v1/admin/escalations/{CONV_REOPEN}", json={"status": "resolved"})
    assert again.status_code == 200
    assert again.json()["status"] == "resolved"
    assert again.json()["resolved_by"] == str(ADMIN_A)
    assert again.json()["resolved_at"] is not None


# --- T021: status filter narrows within the tenant (FR-009) -----------------


def test_status_filter_open_resolved_and_all() -> None:
    _as(TENANT_A, ADMIN_A)
    # resolve one of the two dedicated filter conversations
    client.patch(
        f"/api/v1/admin/escalations/{CONV_FILTER_RESOLVED}", json={"status": "resolved"}
    )

    open_ids = {row["conversation_id"] for row in
                client.get("/api/v1/admin/escalations?status=open").json()}
    resolved_ids = {row["conversation_id"] for row in
                    client.get("/api/v1/admin/escalations?status=resolved").json()}
    all_ids = {row["conversation_id"] for row in
               client.get("/api/v1/admin/escalations").json()}

    assert str(CONV_FILTER_OPEN) in open_ids
    assert str(CONV_FILTER_OPEN) not in resolved_ids
    assert str(CONV_FILTER_RESOLVED) in resolved_ids
    assert str(CONV_FILTER_RESOLVED) not in open_ids
    # no filter returns both
    assert str(CONV_FILTER_OPEN) in all_ids
    assert str(CONV_FILTER_RESOLVED) in all_ids


# --- service guard: invalid status raises (defense in depth, maps to 422) ----


@pytest.mark.asyncio
async def test_service_rejects_invalid_status_value() -> None:
    """The service validates the status before any DB access, so an invalid
    value (should the enum and ESCALATION_STATUSES ever drift) raises
    InvalidEscalationStatusError, which the route maps to 422."""
    from app.services import escalation_service as svc

    with pytest.raises(svc.InvalidEscalationStatusError):
        await svc.set_escalation_status(
            None,  # validity is checked before the session is touched
            tenant_id=uuid.uuid4(),
            conversation_id=uuid.uuid4(),
            new_status="bogus",
            resolved_by=uuid.uuid4(),
        )
