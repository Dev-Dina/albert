"""Escalation persistence + admin view tests (feature 007, US3).

Covers the upsert (insert; re-escalate updates the single row; reason-only →
summary=''), the real agent-dispatch path (M1 remediation: escalation persists
when driven through ``_dispatch_tool`` on a real DB session, not only a direct
``escalate`` call), the admin list/detail endpoints, and cross-tenant isolation.

Uses in-memory SQLite (mirrors the other feature-007 tests).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.admin_widgets import AdminIdentity, require_admin_identity
from app.db.base import Base
from app.db.models.conversation import Conversation
from app.db.models.escalation import Escalation
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.main import app
from app.repositories import escalation_repo
from app.services.agent import _dispatch_tool
from app.tools.escalate import escalate

_ESC_TABLES = ("tenants", "conversations", "escalations")


def _sqlite():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def _create_tables(session: AsyncSession, names) -> None:
    conn = await session.connection()
    tables = [t for t in Base.metadata.sorted_tables if t.name in names]
    await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))


# --- T031: upsert semantics -------------------------------------------------


@pytest.mark.asyncio
async def test_escalate_persists_then_reescalate_updates_single_row() -> None:
    SessionLocal = _sqlite()
    tenant = uuid.uuid4()
    conv = uuid.uuid4()
    async with SessionLocal() as s:
        await _create_tables(s, _ESC_TABLES)
        s.add(Tenant(id=tenant, name="A", slug="a", status="active"))
        await s.commit()

        await escalate(
            tenant_id=str(tenant), conversation_id=str(conv),
            reason="need human", summary="some context", db=s,
        )
        await s.commit()
        rows = (await s.execute(select(Escalation).where(Escalation.tenant_id == tenant))).scalars().all()
        assert len(rows) == 1
        assert rows[0].reason == "need human"
        assert rows[0].summary == "some context"

        # Re-escalate the same conversation → updates the single row (FR-034),
        # and a missing summary is stored as '' (FR-033).
        await escalate(
            tenant_id=str(tenant), conversation_id=str(conv),
            reason="updated reason", summary="", db=s,
        )
        await s.commit()
        rows = (await s.execute(select(Escalation).where(Escalation.tenant_id == tenant))).scalars().all()
        assert len(rows) == 1
        assert rows[0].reason == "updated reason"
        assert rows[0].summary == ""


@pytest.mark.asyncio
async def test_dispatch_escalate_persists_via_real_path() -> None:
    """M1: escalation persists when driven through the agent dispatcher on a real
    session (the production call chain), not only a direct escalate() call."""
    SessionLocal = _sqlite()
    tenant = uuid.uuid4()
    conv = uuid.uuid4()
    async with SessionLocal() as s:
        await _create_tables(s, _ESC_TABLES)
        s.add(Tenant(id=tenant, name="A", slug="a", status="active"))
        await s.commit()

        await _dispatch_tool(
            tool_name="escalate",
            tool_args={"reason": "human please", "summary": "ctx"},
            tenant_id=str(tenant),
            conversation_id=str(conv),
            db=s,
        )
        await s.commit()

        row = (
            await s.execute(select(Escalation).where(Escalation.conversation_id == conv))
        ).scalar_one_or_none()
        assert row is not None
        assert row.reason == "human please"


# --- T032 / T033: admin endpoints + cross-tenant ----------------------------

_SessionLocal = _sqlite()
TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
ADMIN_A = uuid.uuid4()
ADMIN_B = uuid.uuid4()
CONV_A = uuid.uuid4()

client = TestClient(app)
_state = {"ready": False}


async def _ensure_seeded(session: AsyncSession) -> None:
    if _state["ready"]:
        return
    await _create_tables(session, _ESC_TABLES)
    session.add(Tenant(id=TENANT_A, name="Acme", slug="acme", status="active"))
    session.add(Tenant(id=TENANT_B, name="Beta", slug="beta", status="active"))
    session.add(Conversation(id=CONV_A, tenant_id=TENANT_A, session_id=str(CONV_A), status="escalated"))
    await session.flush()
    await escalation_repo.upsert(
        session, tenant_id=TENANT_A, conversation_id=CONV_A,
        reason="Visitor asked for a person", summary="billing question",
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


def test_list_shows_reason_summary_and_status() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.get("/api/v1/admin/escalations")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["reason"] == "Visitor asked for a person"
    assert rows[0]["summary"] == "billing question"
    assert rows[0]["conversation_status"] == "escalated"


def test_get_one_escalation() -> None:
    _as(TENANT_A, ADMIN_A)
    r = client.get(f"/api/v1/admin/escalations/{CONV_A}")
    assert r.status_code == 200, r.text
    assert r.json()["conversation_id"] == str(CONV_A)


def test_cross_tenant_cannot_see_escalations() -> None:
    _as(TENANT_B, ADMIN_B)
    assert client.get("/api/v1/admin/escalations").json() == []
    assert client.get(f"/api/v1/admin/escalations/{CONV_A}").status_code == 404
