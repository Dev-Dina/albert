"""Isolation eval: the runtime app DB role is non-superuser and RLS-enforced.

Phase 6.2A.2. Migration 0001 creates a dedicated ``albert_app`` role
(LOGIN, NOSUPERUSER, NOBYPASSRLS, NOT a table owner). The runtime backend
connects as this role (DATABASE_URL) so FORCE ROW LEVEL SECURITY is actually
enforced — a superuser / BYPASSRLS login silently bypasses every tenant policy.

This proves:
  - the role exists with the correct attributes (non-super, non-bypassrls, login)
  - under that role, RLS scopes reads to ``app.current_tenant``
  - another tenant's rows are invisible, and an unset context returns zero rows

Requires a database migrated to head (the role is created by 0001). The test
connects as the admin/superuser session and uses ``SET ROLE`` to exercise the
app role, so seeding (done as admin) is not blocked by RLS.

    docker compose exec backend uv run pytest evals/isolation/test_app_role.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.tenancy.rls import TENANT_CONTEXT_GUC

_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"
APP_ROLE = "albert_app"

T_A = uuid.UUID("aaaaaaaa-0000-0000-0000-00000000a001")
T_B = uuid.UUID("bbbbbbbb-0000-0000-0000-00000000b001")


@pytest.fixture
def engine():
    import asyncio

    e = create_async_engine(_DB_URL, future=True)
    yield e
    asyncio.run(e.dispose())


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


async def _set_ctx(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    await db.execute(
        text("SELECT set_config(:v, :t, true)"),
        {"v": TENANT_CONTEXT_GUC, "t": str(tenant_id)},
    )


async def _clear_ctx(db: AsyncSession) -> None:
    await db.execute(text("SELECT set_config(:v, '', true)"), {"v": TENANT_CONTEXT_GUC})


async def _count_convs(db: AsyncSession, tenant_id: uuid.UUID) -> int:
    result = await db.execute(
        text("SELECT count(*) FROM conversations WHERE tenant_id = :t"),
        {"t": str(tenant_id)},
    )
    return result.scalar_one()


@pytest.mark.asyncio
async def test_app_role_exists_and_is_non_superuser(db: AsyncSession) -> None:
    """The runtime role exists and cannot bypass RLS."""
    row = (
        await db.execute(
            text(
                "SELECT rolsuper, rolbypassrls, rolcanlogin "
                "FROM pg_roles WHERE rolname = :n"
            ),
            {"n": APP_ROLE},
        )
    ).first()
    assert row is not None, f"runtime role {APP_ROLE!r} missing — migration 0001 must create it"
    rolsuper, rolbypassrls, rolcanlogin = row
    assert rolsuper is False, "app role must be NOSUPERUSER (a superuser bypasses RLS)"
    assert rolbypassrls is False, "app role must be NOBYPASSRLS"
    assert rolcanlogin is True, "app role must be able to LOGIN (runtime connects as it)"


@pytest.mark.asyncio
async def test_app_role_rls_is_enforced(db: AsyncSession) -> None:
    """Under the app role, reads are scoped to app.current_tenant; cross-tenant
    rows are invisible and an unset context returns zero rows (fail-closed)."""
    # Seed two tenants as the admin session (RLS bypassed for seeding only).
    for tid, slug in ((T_A, "approle-a"), (T_B, "approle-b")):
        await db.execute(
            text(
                "INSERT INTO tenants (id, name, slug, status) VALUES "
                "(:id, 'AppRole', :s, 'active') ON CONFLICT (id) DO NOTHING"
            ),
            {"id": str(tid), "s": slug},
        )
        await db.execute(
            text(
                "INSERT INTO conversations (id, tenant_id, session_id) VALUES "
                "(:id, :t, 'sess')"
            ),
            {"id": str(uuid.uuid4()), "t": str(tid)},
        )
    await db.flush()

    # Drop to the runtime app role — RLS is now actively enforced for this session.
    await db.execute(text(f"SET ROLE {APP_ROLE}"))
    try:
        await _set_ctx(db, T_A)
        assert await _count_convs(db, T_A) == 1, "app role must see its own tenant's rows"
        assert await _count_convs(db, T_B) == 0, "app role must NOT see another tenant's rows"

        await _set_ctx(db, T_B)
        assert await _count_convs(db, T_B) == 1
        assert await _count_convs(db, T_A) == 0

        await _clear_ctx(db)
        # Unset context → fail closed (zero rows) even though rows exist.
        assert await _count_convs(db, T_A) == 0
        assert await _count_convs(db, T_B) == 0
    finally:
        await db.execute(text("RESET ROLE"))

    await db.rollback()
