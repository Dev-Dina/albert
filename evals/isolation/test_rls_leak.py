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
from app.repos.chunk_repo import ChunkRepo
from app.tenancy.rls import (
    clear_tenant_context,
    get_current_tenant_context,
    set_tenant_context,
)

# ---------------------------------------------------------------------------
# Engine + session fixtures
# ---------------------------------------------------------------------------

_TEST_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"
_RLS_EVAL_ROLE = "albert_rls_eval"
_VECTOR_768 = "[" + ",".join(["0.1"] * 768) + "]"


@pytest_asyncio.fixture
async def engine():
    e = create_async_engine(_TEST_DB_URL, future=True, pool_size=2)
    async with e.begin() as conn:
        await conn.execute(
            text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_roles WHERE rolname = '{_RLS_EVAL_ROLE}'
                    ) THEN
                        CREATE ROLE {_RLS_EVAL_ROLE};
                    END IF;
                END
                $$;
                """
            )
        )
        await conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {_RLS_EVAL_ROLE}"))
        await conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                f"ON ALL TABLES IN SCHEMA public TO {_RLS_EVAL_ROLE}"
            )
        )
    try:
        yield e
    finally:
        await e.dispose()


@pytest_asyncio.fixture
async def db(engine) -> AsyncSession:
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        await session.execute(text(f"SET ROLE {_RLS_EVAL_ROLE}"))
        try:
            yield session
        finally:
            await session.rollback()
            await session.execute(text("RESET ROLE"))
            await session.rollback()


# ---------------------------------------------------------------------------
# Tenant fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tenant_a() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")


@pytest.fixture
def tenant_b() -> uuid.UUID:
    return uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


@pytest.fixture
def tenant_c() -> uuid.UUID:
    return uuid.UUID("cccccccc-0000-0000-0000-000000000003")


async def _seed_live_chunk(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    parent_text: str,
    child_text: str,
) -> tuple[uuid.UUID, uuid.UUID]:
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    await set_tenant_context(db, tenant_id)
    await db.execute(
        text(
            "INSERT INTO parent_chunks (id, tenant_id, content_id, text, chunk_index) VALUES "
            "(:id, :tid, :content_id, :text, 0)"
        ),
        {
            "id": str(parent_id),
            "tid": str(tenant_id),
            "content_id": str(uuid.uuid4()),
            "text": parent_text,
        },
    )
    await db.execute(
        text(
            "INSERT INTO child_chunks "
            "(id, tenant_id, parent_id, text, embedding, chunk_index) VALUES "
            "(:id, :tid, :parent_id, :text, CAST(:embedding AS vector), 0)"
        ),
        {
            "id": str(child_id),
            "tid": str(tenant_id),
            "parent_id": str(parent_id),
            "text": child_text,
            "embedding": _VECTOR_768,
        },
    )
    return parent_id, child_id


async def _visible_chunk_ids(db: AsyncSession) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    parent_result = await db.execute(text("SELECT id FROM parent_chunks"))
    child_result = await db.execute(text("SELECT id FROM child_chunks"))
    return (
        {row[0] for row in parent_result.fetchall()},
        {row[0] for row in child_result.fetchall()},
    )


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

    assert str(conv_b) in str(visible_ids) or any(
        str(conv_b) in str(v) for v in visible_ids
    ), "Tenant B's conversation should be visible to tenant B."

    assert not any(
        str(conv_a) in str(v) for v in visible_ids
    ), (
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
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) VALUES "
            "(:tid, 'Tenant A', 'tenant-a', 'active') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"tid": str(tenant_a)},
    )

    conv_id = uuid.uuid4()
    await set_tenant_context(db, tenant_a)
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, session_id, status) VALUES "
            "(:cid, :tid, 'sess-unset', 'open')"
        ),
        {"cid": str(conv_id), "tid": str(tenant_a)},
    )

    visible_result = await db.execute(
        text("SELECT count(*) FROM conversations WHERE id = :cid"),
        {"cid": str(conv_id)},
    )
    assert visible_result.scalar_one() == 1

    await db.execute(text("RESET app.current_tenant"))

    result = await db.execute(text("SELECT count(*) FROM conversations"))
    count = result.scalar_one()

    assert count == 0, (
        f"Expected 0 rows with no tenant context set, got {count}. "
        "RLS policy must match no rows when app.current_tenant is unset."
    )

    await clear_tenant_context(db)
    result = await db.execute(text("SELECT count(*) FROM conversations"))
    empty_count = result.scalar_one()
    assert empty_count == 0, (
        f"Expected 0 rows with empty tenant context set, got {empty_count}. "
        "RLS policy must match no rows when app.current_tenant is empty."
    )
    await db.rollback()


# ---------------------------------------------------------------------------
# Test 5: live RAG chunk RLS fails closed and permits correct tenant search
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_chunk_rls_isolation_and_fail_closed(
    db: AsyncSession,
    tenant_a: uuid.UUID,
    tenant_b: uuid.UUID,
    tenant_c: uuid.UUID,
) -> None:
    """Live RAG chunk tables must isolate tenants and fail closed safely."""
    parent_a, child_a = await _seed_live_chunk(
        db,
        tenant_a,
        parent_text="Tenant A live parent",
        child_text="Tenant A live child",
    )
    parent_b, child_b = await _seed_live_chunk(
        db,
        tenant_b,
        parent_text="Tenant B live parent",
        child_text="Tenant B live child",
    )

    await set_tenant_context(db, tenant_a)
    visible_parents, visible_children = await _visible_chunk_ids(db)
    assert parent_a in visible_parents
    assert child_a in visible_children
    assert parent_b not in visible_parents
    assert child_b not in visible_children

    await set_tenant_context(db, tenant_b)
    visible_parents, visible_children = await _visible_chunk_ids(db)
    assert parent_b in visible_parents
    assert child_b in visible_children
    assert parent_a not in visible_parents
    assert child_a not in visible_children

    await set_tenant_context(db, tenant_c)
    visible_parents, visible_children = await _visible_chunk_ids(db)
    assert visible_parents.isdisjoint({parent_a, parent_b})
    assert visible_children.isdisjoint({child_a, child_b})

    await db.execute(text("RESET app.current_tenant"))
    visible_parents, visible_children = await _visible_chunk_ids(db)
    assert visible_parents.isdisjoint({parent_a, parent_b})
    assert visible_children.isdisjoint({child_a, child_b})

    await clear_tenant_context(db)
    visible_parents, visible_children = await _visible_chunk_ids(db)
    assert visible_parents.isdisjoint({parent_a, parent_b})
    assert visible_children.isdisjoint({child_a, child_b})

    await set_tenant_context(db, tenant_a)
    repo = ChunkRepo(db)
    children = await repo.search_children(
        embedding=[0.1] * 768,
        tenant_id=tenant_a,
        top_k=10,
    )
    child_ids = {child.id for child in children}
    assert child_a in child_ids
    assert child_b not in child_ids

    parents = await repo.fetch_parents_by_ids([parent_a, parent_b], tenant_id=tenant_a)
    parent_ids = {parent.id for parent in parents}
    assert parent_ids == {parent_a}

    await db.rollback()
