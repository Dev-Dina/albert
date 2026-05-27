"""Unit tests for add_tenant_admin and remove_tenant_admin service functions.

These tests use an in-memory SQLite database via SQLAlchemy so they run
without a running Postgres instance.  They exercise the service layer directly,
covering all guard conditions required by the spec.

Run:
    uv run pytest backend/tests/test_tenant_admin_mgmt.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Role
from app.db.base import Base
from app.db.models.membership import TenantMembership
from app.db.models.tenant import Tenant
from app.db.models.user import User
from app.tenancy.provisioning import (
    AdminNotFoundError,
    LastAdminError,
    add_tenant_admin,
    remove_tenant_admin,
)

# ---------------------------------------------------------------------------
# In-memory SQLite engine (no Postgres required)
# ---------------------------------------------------------------------------

_ENGINE = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)


# Only the platform tables these tests exercise. The full Base.metadata also holds
# pgvector/JSONB tables (chunks, guardrail/widget configs) that SQLite cannot compile;
# those paths require Postgres. Scope create/drop so this stays an in-memory unit test.
_PLATFORM_TABLES = ("users", "tenants", "tenant_memberships", "audit_logs")


@pytest_asyncio.fixture(autouse=True, scope="module")
async def create_tables():
    tables = [t for t in Base.metadata.sorted_tables if t.name in _PLATFORM_TABLES]
    async with _ENGINE.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
    yield
    async with _ENGINE.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.drop_all(c, tables=tables))


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
        await session.rollback()


# ---------------------------------------------------------------------------
# Fixtures: manager user + active tenant
# ---------------------------------------------------------------------------

MANAGER_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True, scope="module")
async def seed_base_data():
    """Insert a manager user and an active tenant once for the whole module."""
    SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        session.add(User(id=MANAGER_ID, email="manager@test.local", hashed_password="x", is_active=True))
        session.add(Tenant(id=TENANT_ID, name="Test Tenant", slug="test-tenant", status="active"))
        await session.commit()


# ---------------------------------------------------------------------------
# T009: add admin success
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_admin_success(db: AsyncSession) -> None:
    user, tid = await add_tenant_admin(
        db=db,
        actor_user_id=MANAGER_ID,
        tenant_id=TENANT_ID,
        email="newadmin@test.local",
        password="secret123",
    )
    assert user.email == "newadmin@test.local"
    assert tid == TENANT_ID

    from sqlalchemy import select
    result = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == TENANT_ID,
            TenantMembership.user_id == user.id,
        )
    )
    membership = result.scalar_one_or_none()
    assert membership is not None
    assert membership.role == Role.tenant_admin.value


# ---------------------------------------------------------------------------
# T010: add admin rejects suspended tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_admin_rejects_suspended_tenant(db: AsyncSession) -> None:
    suspended_id = uuid.uuid4()
    db.add(Tenant(id=suspended_id, name="Suspended Co", slug="suspended-co", status="suspended"))
    await db.flush()

    with pytest.raises(ValueError, match="suspended"):
        await add_tenant_admin(
            db=db,
            actor_user_id=MANAGER_ID,
            tenant_id=suspended_id,
            email="admin@suspended.local",
            password="pass",
        )


# ---------------------------------------------------------------------------
# T011: add admin rejects erased tenant
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_admin_rejects_erased_tenant(db: AsyncSession) -> None:
    erased_id = uuid.uuid4()
    db.add(Tenant(id=erased_id, name="Erased Co", slug="erased-co", status="erased"))
    await db.flush()

    with pytest.raises(ValueError, match="erased"):
        await add_tenant_admin(
            db=db,
            actor_user_id=MANAGER_ID,
            tenant_id=erased_id,
            email="admin@erased.local",
            password="pass",
        )


# ---------------------------------------------------------------------------
# T012: add admin rejects duplicate email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_admin_rejects_duplicate_email(db: AsyncSession) -> None:
    existing_user = User(id=uuid.uuid4(), email="duplicate@test.local", hashed_password="x", is_active=True)
    db.add(existing_user)
    await db.flush()

    with pytest.raises(ValueError, match="already exists"):
        await add_tenant_admin(
            db=db,
            actor_user_id=MANAGER_ID,
            tenant_id=TENANT_ID,
            email="duplicate@test.local",
            password="pass",
        )


# ---------------------------------------------------------------------------
# T013: remove admin success — user account preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_admin_success(db: AsyncSession) -> None:
    from sqlalchemy import select

    # Create two admins on a dedicated tenant so remove doesn't hit last-admin guard.
    tenant_id = uuid.uuid4()
    db.add(Tenant(id=tenant_id, name="Two Admin Tenant", slug="two-admin-tenant", status="active"))
    admin1_id = uuid.uuid4()
    admin2_id = uuid.uuid4()
    db.add(User(id=admin1_id, email="admin1@two.local", hashed_password="x", is_active=True))
    db.add(User(id=admin2_id, email="admin2@two.local", hashed_password="x", is_active=True))
    db.add(TenantMembership(id=uuid.uuid4(), tenant_id=tenant_id, user_id=admin1_id, role=Role.tenant_admin.value))
    db.add(TenantMembership(id=uuid.uuid4(), tenant_id=tenant_id, user_id=admin2_id, role=Role.tenant_admin.value))
    await db.flush()

    removed = await remove_tenant_admin(
        db=db, actor_user_id=MANAGER_ID, tenant_id=tenant_id, user_id=admin1_id
    )
    assert removed == admin1_id

    # Membership deleted.
    m = await db.execute(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == admin1_id,
        )
    )
    assert m.scalar_one_or_none() is None

    # User account preserved.
    u = await db.execute(select(User).where(User.id == admin1_id))
    assert u.scalar_one_or_none() is not None


# ---------------------------------------------------------------------------
# T014: remove last admin is blocked
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_last_admin_blocked(db: AsyncSession) -> None:
    tenant_id = uuid.uuid4()
    db.add(Tenant(id=tenant_id, name="Solo Tenant", slug="solo-tenant", status="active"))
    only_admin_id = uuid.uuid4()
    db.add(User(id=only_admin_id, email="solo@test.local", hashed_password="x", is_active=True))
    db.add(TenantMembership(id=uuid.uuid4(), tenant_id=tenant_id, user_id=only_admin_id, role=Role.tenant_admin.value))
    await db.flush()

    with pytest.raises(LastAdminError):
        await remove_tenant_admin(
            db=db, actor_user_id=MANAGER_ID, tenant_id=tenant_id, user_id=only_admin_id
        )


# ---------------------------------------------------------------------------
# T015: remove non-existent membership raises not found
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remove_nonexistent_membership_raises(db: AsyncSession) -> None:
    with pytest.raises(AdminNotFoundError):
        await remove_tenant_admin(
            db=db,
            actor_user_id=MANAGER_ID,
            tenant_id=TENANT_ID,
            user_id=uuid.uuid4(),  # random user — definitely not an admin
        )
