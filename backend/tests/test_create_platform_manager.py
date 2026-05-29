"""Unit tests for create_platform_manager service function.

Uses in-memory SQLite (no Postgres required).

Run:
    uv run pytest backend/tests/test_create_platform_manager.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.models import Role
from app.db.base import Base
from app.db.models.membership import TenantMembership
from app.db.models.user import User
from app.tenancy.provisioning import create_platform_manager

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


ACTOR_ID = uuid.uuid4()


@pytest_asyncio.fixture(autouse=True, scope="module")
async def seed_actor():
    SessionLocal = async_sessionmaker(bind=_ENGINE, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        session.add(User(id=ACTOR_ID, email="actor@test.local", hashed_password="x", is_active=True))
        await session.commit()


# ---------------------------------------------------------------------------
# Success: new user gets platform_role=tenant_manager and NO tenant membership
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_manager_success(db: AsyncSession) -> None:
    manager = await create_platform_manager(
        db=db,
        actor_user_id=ACTOR_ID,
        email="newmanager@test.local",
        password="secret123",
    )
    assert manager.email == "newmanager@test.local"
    # Manager is platform-scoped via users.platform_role only.
    assert manager.platform_role == Role.tenant_manager.value

    # Memberships are strictly tenant-scoped — a manager has none.
    result = await db.execute(
        select(TenantMembership).where(TenantMembership.user_id == manager.id)
    )
    assert result.scalar_one_or_none() is None


# ---------------------------------------------------------------------------
# Duplicate email is rejected
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_manager_rejects_duplicate_email(db: AsyncSession) -> None:
    db.add(User(id=uuid.uuid4(), email="taken@test.local", hashed_password="x", is_active=True))
    await db.flush()

    with pytest.raises(ValueError, match="already exists"):
        await create_platform_manager(
            db=db,
            actor_user_id=ACTOR_ID,
            email="taken@test.local",
            password="pass",
        )
