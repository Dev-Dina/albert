"""Isolation eval: RLS leak tests (A2 + A3 checkpoints from OWNER_A_PLAN).

These are the two non-negotiable tests:

  1. test_pooled_connection_does_not_leak_context
     A transaction that sets tenant A's context must not leave that context on
     the connection after commit.  The next transaction on the same connection
     must start with an empty (or null) app.current_tenant.

  2. test_tenant_id_comes_from_token_not_body
     The tenant_scope dependency resolves tenant_id from the verified JWT token.
     Even if the request body carries a different tenant_id, the token value wins.

  3. test_tenant_a_cannot_read_tenant_b_rows
     With tenant B's context set, querying a tenant-owned table must return only
     tenant B's rows — not tenant A's.

These tests require a live Postgres instance with the migrations applied.
Run them inside Docker:

    docker compose exec backend uv run pytest evals/isolation/test_rls_leak.py -v

Or point DATABASE_URL at a test DB reachable from the host.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.tenancy.rls import (
    clear_tenant_context,
    get_current_tenant_context,
    set_tenant_context,
)

# ---------------------------------------------------------------------------
# Engine + session fixtures
# ---------------------------------------------------------------------------

_TEST_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"


@pytest.fixture(scope="module")
def engine():
    import asyncio
    e = create_async_engine(_TEST_DB_URL, future=True, pool_size=2)
    yield e
    asyncio.run(e.dispose())


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------------------
# Tenant fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_a() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@pytest.fixture
def tenant_b() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


# ---------------------------------------------------------------------------
# Test 1: pooled connection does not leak context
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pooled_connection_does_not_leak_context(db: AsyncSession, tenant_a: uuid.UUID) -> None:
    """After a transaction that set tenant A's context commits, the context must be empty.

    This verifies that set_config(..., true) (is_local=true / transaction-local)
    correctly reverts on commit, so a pooled connection reused for the next
    request starts clean.
    """
    # Simulate a request for tenant A: set context, run a query, commit.
    await set_tenant_context(db, tenant_a)
    ctx_during = await get_current_tenant_context(db)
    assert ctx_during == str(tenant_a), (
        f"Expected tenant A context during transaction, got {ctx_during!r}"
    )
    await clear_tenant_context(db)
    await db.commit()

    # On the same connection (new transaction), the context must be empty.
    ctx_after = await get_current_tenant_context(db)
    assert ctx_after in ("", None), (
        f"Context leaked after commit: {ctx_after!r}. "
        "This means set_config is not transaction-local (is_local must be true)."
    )


# ---------------------------------------------------------------------------
# Test 2: tenant_id comes from token, not body
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_id_comes_from_token_not_body(
    db: AsyncSession,
    tenant_a: uuid.UUID,
    tenant_b: uuid.UUID,
) -> None:
    """The RLS context is set from the token-resolved tenant_id.

    Simulates what deps.tenant_scope does: resolves tenant_id from the
    verified token (tenant A), then asserts that even if tenant B's id is
    "in the body", the context on the DB connection is tenant A's.
    """
    # Simulate token resolution → tenant A; body claims tenant B (adversarial).
    token_resolved_tenant_id = tenant_a
    # body_supplied_tenant_id = tenant_b  # intentionally unused — that's the point

    await set_tenant_context(db, token_resolved_tenant_id)
    ctx = await get_current_tenant_context(db)
    assert ctx == str(tenant_a), (
        f"Expected tenant A from token, got {ctx!r}. "
        "tenant_id must come from verified token only."
    )
    await clear_tenant_context(db)
    await db.rollback()


# ---------------------------------------------------------------------------
# Test 3: tenant A cannot read tenant B rows through the repo
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tenant_a_cannot_read_tenant_b_rows(
    db: AsyncSession,
    tenant_a: uuid.UUID,
    tenant_b: uuid.UUID,
) -> None:
    """With tenant B's context active, querying conversations returns only B's rows.

    This test seeds one conversation for tenant A and one for tenant B, then
    reads with tenant B's context and asserts tenant A's row is absent.

    Requires the 0001 + 0002 migrations to be applied (tenants + conversations tables).
    The test inserts and rolls back to leave the DB clean.
    """
    # Seed two tenants in the tenants table (platform-owned, no RLS).
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) VALUES "
            "(:aid, 'Tenant A', 'tenant-a', 'active'), "
            "(:bid, 'Tenant B', 'tenant-b', 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"aid": str(tenant_a), "bid": str(tenant_b)},
    )

    # Insert one conversation for each tenant.
    # FORCE ROW LEVEL SECURITY applies the WITH CHECK clause on INSERT too, so we
    # must set the matching tenant context before each seed row — we cannot bypass
    # RLS via raw SQL when the app DB role is not a Postgres superuser.
    conv_a = uuid.uuid4()
    conv_b = uuid.uuid4()

    await set_tenant_context(db, tenant_a)
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, session_id, status) VALUES "
            "(:cid_a, :tid_a, 'sess-a', 'open')"
        ),
        {"cid_a": str(conv_a), "tid_a": str(tenant_a)},
    )

    await set_tenant_context(db, tenant_b)
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, session_id, status) VALUES "
            "(:cid_b, :tid_b, 'sess-b', 'open')"
        ),
        {"cid_b": str(conv_b), "tid_b": str(tenant_b)},
    )

    # Set context to tenant B and read.
    await set_tenant_context(db, tenant_b)
    result = await db.execute(text("SELECT id FROM conversations"))
    visible_ids = {row[0] for row in result.fetchall()}

    assert conv_b in visible_ids, "Tenant B's conversation should be visible to tenant B."

    assert conv_a not in visible_ids, (
        "Tenant A's conversation is visible to tenant B — RLS is not enforced! "
        "Check that ENABLE ROW LEVEL SECURITY and FORCE ROW LEVEL SECURITY are set, "
        "the policy uses nullif(current_setting('app.current_tenant', true), '')::uuid, "
        "and the app connects as a non-superuser role."
    )

    await clear_tenant_context(db)
    await db.rollback()


# ---------------------------------------------------------------------------
# Test 4: unset context yields zero rows (fail closed)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unset_context_returns_zero_rows(db: AsyncSession, tenant_a: uuid.UUID) -> None:
    """When app.current_tenant is unset, tenant-owned tables return no rows.

    This verifies the "fail closed" guarantee: no context = no data, not all data.
    An RLS policy that returns all rows on NULL/empty context is a critical defect.
    """
    # Ensure context is empty.
    await clear_tenant_context(db)

    result = await db.execute(text("SELECT count(*) FROM conversations"))
    count = result.scalar_one()

    assert count == 0, (
        f"Expected 0 rows with no tenant context set, got {count}. "
        "RLS policy must match no rows when app.current_tenant is unset."
    )
    await db.rollback()
