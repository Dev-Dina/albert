"""Isolation eval: audit log checkpoint test (A5 from OWNER_A_PLAN).

Verifies that every platform manager action is recorded in audit_logs
with the correct actor_user_id.

Run inside Docker:

    docker compose exec backend uv run pytest evals/isolation/test_audit.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.tenancy.audit import record_audit
from app.tenancy.provisioning import provision_tenant

_TEST_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"

MANAGER_ID = uuid.UUID("cccccccc-0000-0000-0000-000000000001")


# Function-scoped: pytest-asyncio runs each test in its own event loop, so a
# module-scoped engine would bind its pooled connection to the first test's
# loop and the next test fails with "attached to a different loop".
@pytest.fixture
def engine():
    import asyncio
    e = create_async_engine(_TEST_DB_URL, future=True)
    yield e
    asyncio.run(e.dispose())


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# A5 checkpoint: every manager action is audit-logged with actor_user_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_action_is_audited(db: AsyncSession) -> None:
    """A5 checkpoint: provision_tenant() writes an audit_logs row with actor_user_id.

    Calls the real provisioning function and asserts the audit entry was
    written with the correct actor_user_id and action = 'tenant.provision'.
    Rolls back at the end so the DB is left clean.
    """
    # Seed manager user (platform table — no RLS required).
    await db.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) VALUES "
            "(:id, 'audit-mgr@test.local', 'x', true) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(MANAGER_ID)},
    )
    await db.flush()

    unique_suffix = uuid.uuid4().hex[:8]
    tenant, _ = await provision_tenant(
        db=db,
        actor_user_id=MANAGER_ID,
        name=f"Audit Test Tenant {unique_suffix}",
        first_admin_email=f"admin-{unique_suffix}@audit-test.local",
        first_admin_password="test-pass-audit-1234",
    )

    result = await db.execute(
        text(
            "SELECT actor_user_id, action FROM audit_logs "
            "WHERE actor_user_id = :actor "
            "  AND target_tenant_id = :tid "
            "  AND action = 'tenant.provision'"
        ),
        {"actor": str(MANAGER_ID), "tid": str(tenant.id)},
    )
    row = result.fetchone()

    assert row is not None, (
        "No audit_logs row for tenant.provision. "
        "Every platform manager action must be audit-logged with actor_user_id."
    )
    assert str(row[0]) == str(MANAGER_ID), (
        f"audit_logs.actor_user_id = {row[0]!r}, expected {MANAGER_ID!r}. "
        "actor_user_id must match the authenticated manager — anonymous actions are forbidden."
    )

    await db.rollback()


# ---------------------------------------------------------------------------
# Structural: record_audit always stores actor + meta correctly
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_record_audit_stores_actor_and_meta(db: AsyncSession) -> None:
    """record_audit() must persist actor_user_id and meta without modification.

    This test does not depend on provisioning; it hits audit.py directly
    so failures point unambiguously at the audit writer, not the caller.
    """
    actor = uuid.uuid4()
    fake_tenant = uuid.uuid4()

    # Seed the actor user so the FK constraint is satisfied.
    await db.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) VALUES "
            "(:id, :email, 'x', true) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(actor), "email": f"audit-{actor.hex[:8]}@test.local"},
    )
    # Seed the target tenant so the FK constraint is satisfied.
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) VALUES "
            "(:id, 'Audit Struct Tenant', :slug, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(fake_tenant), "slug": f"audit-struct-{actor.hex[:8]}"},
    )
    await db.flush()

    entry = await record_audit(
        db=db,
        actor_user_id=actor,
        target_tenant_id=fake_tenant,
        action="test.audit.write",
        meta={"key": "value", "nested": {"n": 1}},
    )

    assert entry.actor_user_id == actor, "actor_user_id must be stored exactly as provided."
    assert entry.action == "test.audit.write"
    assert entry.meta == {"key": "value", "nested": {"n": 1}}, "meta must be stored without modification."
    assert entry.id is not None, "audit entry must have a generated id after flush."

    await db.rollback()
