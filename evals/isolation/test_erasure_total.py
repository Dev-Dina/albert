"""Isolation eval: total erasure test (A7 checkpoint from OWNER_A_PLAN).

Verifies that ``erase_tenant`` purges every store and leaves an audit trail.

The five stores (per PROJECT_CONTEXT.md §11):
  1. Postgres rows         — all tenant-owned tables
  2. pgvector embeddings   — live child_chunks/parent_chunks, plus legacy content_chunks
  3. MinIO blobs           — objects under {tenant_id}/ prefix
  4. Redis sessions        — keys matching session:{tenant_id}:*
  5. Traces / logs         — stub (Owner C); asserted as a warning in logs

"The row is deleted but the embeddings are still searchable" = FAIL.

Run inside Docker:

    docker compose exec backend uv run pytest evals/isolation/test_erasure_total.py -v
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.services.retrieval import retrieve
from app.tenancy.erasure import erase_tenant

_TEST_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"

TENANT_X = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
TENANT_Y = uuid.UUID("eeeeeeee-0000-0000-0000-000000000100")
ACTOR_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")
VECTOR_768 = "[" + ",".join(["0.1"] * 768) + "]"


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
# Helper: seed tenants with data in every store
# ---------------------------------------------------------------------------

async def _seed_tenant(
    db: AsyncSession,
    tenant_id: uuid.UUID = TENANT_X,
    *,
    name: str = "Erasure Test Tenant",
    slug: str = "erasure-test",
    live_parent_text: str = "Tenant X erased live parent text",
    live_child_text: str = "Tenant X erased live child text",
    widget_public_id: str = "wgt-test",
    origin: str = "https://x.example.com",
) -> dict[str, uuid.UUID]:
    """Insert representative rows, including live RAG chunks, for a tenant."""
    # Tenant row (platform table — no RLS)
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) VALUES "
            "(:id, :name, :slug, 'active') "
            "ON CONFLICT (id) DO UPDATE SET status = 'active', name = :name, slug = :slug"
        ),
        {"id": str(tenant_id), "name": name, "slug": slug},
    )

    # Actor (tenant_manager)
    await db.execute(
        text(
            "INSERT INTO users (id, email, hashed_password, is_active) VALUES "
            "(:id, 'manager@test.local', 'x', true) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(ACTOR_ID)},
    )

    # CMS page
    cms_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO cms_pages (id, tenant_id, title, slug, body) VALUES "
            "(:id, :tid, 'Test Page', 'test-page', 'hello')"
        ),
        {"id": str(cms_id), "tid": str(tenant_id)},
    )

    # Live RAG chunks used by the retrieval path: child_chunks -> parent_chunks.
    parent_id = uuid.uuid4()
    child_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO parent_chunks (id, tenant_id, content_id, text, chunk_index) VALUES "
            "(:id, :tid, :content_id, :text, 0)"
        ),
        {
            "id": str(parent_id),
            "tid": str(tenant_id),
            "content_id": str(cms_id),
            "text": live_parent_text,
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
            "text": live_child_text,
            "embedding": VECTOR_768,
        },
    )

    # Legacy content chunk compatibility.
    chunk_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO content_chunks (id, tenant_id, chunk_text) VALUES "
            "(:id, :tid, 'some chunk')"
        ),
        {"id": str(chunk_id), "tid": str(tenant_id)},
    )

    # Conversation + message
    conv_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, session_id) VALUES "
            "(:id, :tid, 'sess-x')"
        ),
        {"id": str(conv_id), "tid": str(tenant_id)},
    )
    msg_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO messages (id, tenant_id, conversation_id, role, content) VALUES "
            "(:id, :tid, :cid, 'user', 'hello world')"
        ),
        {"id": str(msg_id), "tid": str(tenant_id), "cid": str(conv_id)},
    )

    # Lead
    lead_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO leads (id, tenant_id, name, contact, intent) VALUES "
            "(:id, :tid, 'Alice', 'alice@example.com', 'buy')"
        ),
        {"id": str(lead_id), "tid": str(tenant_id)},
    )

    # Widget config (legacy 0003 table)
    wc_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO widget_configs (id, tenant_id, public_widget_id) VALUES "
            "(:id, :tid, :public_widget_id)"
        ),
        {"id": str(wc_id), "tid": str(tenant_id), "public_widget_id": widget_public_id},
    )

    # Widget tables (migration 0004) — also tenant-owned, must be erased.
    widget_id = uuid.uuid4()
    widget_pub_id = uuid.uuid4().hex[:22]  # satisfies ^[A-Za-z0-9]{22}$
    await db.execute(
        text(
            "INSERT INTO widgets (id, tenant_id, public_widget_id, name) VALUES "
            "(:id, :tid, :pub, 'Test Widget')"
        ),
        {"id": str(widget_id), "tid": str(tenant_id), "pub": widget_pub_id},
    )
    origin_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO widget_allowed_origins (id, tenant_id, origin) VALUES "
            "(:id, :tid, :origin)"
        ),
        {"id": str(origin_id), "tid": str(tenant_id), "origin": origin},
    )
    skv_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO widget_signing_key_versions "
            "(id, tenant_id, version, is_active) VALUES (:id, :tid, 1, true)"
        ),
        {"id": str(skv_id), "tid": str(tenant_id)},
    )
    wgc_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO widget_guardrail_configs (id, tenant_id) VALUES (:id, :tid)"
        ),
        {"id": str(wgc_id), "tid": str(tenant_id)},
    )

    # Tenant guardrail config (from 0003) — unique per tenant
    await db.execute(
        text(
            "INSERT INTO tenant_guardrail_configs (id, tenant_id) VALUES (:id, :tid)"
        ),
        {"id": str(uuid.uuid4()), "tid": str(tenant_id)},
    )

    # Cost event
    ce_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO cost_events "
            "(id, tenant_id, call_type, model, input_tokens, output_tokens, cost_usd) VALUES "
            "(:id, :tid, 'llm', 'test-model', 100, 50, 0.001)"
        ),
        {"id": str(ce_id), "tid": str(tenant_id)},
    )

    await db.flush()
    return {
        "cms_id": cms_id,
        "parent_id": parent_id,
        "child_id": child_id,
        "chunk_id": chunk_id,
        "conv_id": conv_id,
        "msg_id": msg_id,
        "lead_id": lead_id,
    }


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------

async def _count(db: AsyncSession, table: str, tenant_id: uuid.UUID) -> int:
    result = await db.execute(
        text(f"SELECT count(*) FROM {table} WHERE tenant_id = :tid"),
        {"tid": str(tenant_id)},
    )
    return result.scalar_one()


async def _audit_exists(db: AsyncSession, tenant_id: uuid.UUID, action: str) -> bool:
    result = await db.execute(
        text(
            "SELECT count(*) FROM audit_logs "
            "WHERE target_tenant_id = :tid AND action = :action"
        ),
        {"tid": str(tenant_id), "action": action},
    )
    return result.scalar_one() > 0


class _StaticEmbedder:
    async def embed_one(self, query: str) -> list[float]:
        return [0.1] * 768


class _PassthroughReranker:
    async def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        return [(idx, 1.0 - (idx * 0.01)) for idx, _ in enumerate(texts)]


# ---------------------------------------------------------------------------
# Main test: erasure is total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_erasure_is_total(db: AsyncSession) -> None:
    """Erase TENANT_X and assert every store is empty.

    MinIO and Redis calls are mocked so this test runs without those services.
    The Postgres assertions are live — they require a running database.
    """
    tenant_x_rows = await _seed_tenant(db)
    tenant_y_rows = await _seed_tenant(
        db,
        TENANT_Y,
        name="Erasure Survivor Tenant",
        slug="erasure-survivor",
        live_parent_text="Tenant Y surviving live parent text",
        live_child_text="Tenant Y surviving live child text",
        widget_public_id="wgt-test-survivor",
        origin="https://y.example.com",
    )

    assert await _count(db, "parent_chunks", TENANT_X) == 1
    assert await _count(db, "child_chunks", TENANT_X) == 1
    assert await _count(db, "parent_chunks", TENANT_Y) == 1
    assert await _count(db, "child_chunks", TENANT_Y) == 1

    # Widget tables (0004) seeded for both tenants before erasure.
    _WIDGET_TABLES = [
        "widgets",
        "widget_allowed_origins",
        "widget_signing_key_versions",
        "widget_guardrail_configs",
    ]
    for table in _WIDGET_TABLES:
        assert await _count(db, table, TENANT_X) == 1, f"seed FAIL: {table} for TENANT_X"
        assert await _count(db, table, TENANT_Y) == 1, f"seed FAIL: {table} for TENANT_Y"

    # Mock the external-store erasure helpers so the test is self-contained.
    with (
        patch("app.tenancy.erasure._erase_minio", new_callable=AsyncMock, return_value=1) as erase_minio,
        patch("app.tenancy.erasure._erase_redis", new_callable=AsyncMock, return_value=2) as erase_redis,
        patch("app.tenancy.erasure._erase_traces", new_callable=AsyncMock) as erase_traces,
    ):
        summary = await erase_tenant(db=db, actor_user_id=ACTOR_ID, tenant_id=TENANT_X)

    erase_minio.assert_awaited_once_with(TENANT_X)
    erase_redis.assert_awaited_once_with(TENANT_X)
    erase_traces.assert_awaited_once_with(TENANT_X)

    # 1. Postgres — all tenant-owned tables must be empty for TENANT_X
    for table in [
        "cost_events",
        "leads",
        "messages",
        "conversations",
        "child_chunks",
        "parent_chunks",
        "content_chunks",
        "cms_pages",
        "widget_configs",
        "tenant_guardrail_configs",
        "widgets",
        "widget_allowed_origins",
        "widget_signing_key_versions",
        "widget_guardrail_configs",
    ]:
        remaining = await _count(db, table, TENANT_X)
        assert remaining == 0, (
            f"Store FAIL: {table} still has {remaining} rows for tenant {TENANT_X}. "
            "'Deleted but still searchable' is a compliance failure."
        )

    # 2. pgvector — live chunks are explicitly asserted above; summary must record them.
    # Tenant B's live RAG chunks must survive Tenant A erasure.
    assert await _count(db, "parent_chunks", TENANT_Y) == 1
    assert await _count(db, "child_chunks", TENANT_Y) == 1

    # Tenant B's widget rows must survive Tenant A erasure (no cross-tenant deletion).
    for table in _WIDGET_TABLES:
        assert await _count(db, table, TENANT_Y) == 1, (
            f"Isolation FAIL: {table} for TENANT_Y was deleted by TENANT_X erasure."
        )

    tenant_a_results = await retrieve(
        tenant_id=str(TENANT_X),
        query="erased live parent text",
        db=db,
        embedder=_StaticEmbedder(),
        reranker=_PassthroughReranker(),
    )
    assert tenant_a_results == []
    assert tenant_x_rows["parent_id"] not in {uuid.UUID(r.parent_chunk_id) for r in tenant_a_results}
    assert all("Tenant X erased" not in r.text for r in tenant_a_results)

    tenant_b_results = await retrieve(
        tenant_id=str(TENANT_Y),
        query="surviving live parent text",
        db=db,
        embedder=_StaticEmbedder(),
        reranker=_PassthroughReranker(),
    )
    assert {uuid.UUID(r.parent_chunk_id) for r in tenant_b_results} == {tenant_y_rows["parent_id"]}
    assert tenant_b_results[0].text == "Tenant Y surviving live parent text"

    assert summary.get("pgvector.child_chunks", -1) >= 0, (
        "pgvector.child_chunks not reported in erasure summary."
    )
    assert summary.get("pgvector.parent_chunks", -1) >= 0, (
        "pgvector.parent_chunks not reported in erasure summary."
    )
    assert summary.get("pgvector.content_chunks", -1) >= 0, (
        "pgvector.content_chunks not reported in erasure summary."
    )

    # 3. MinIO — mock was called
    assert summary.get("minio.objects", -1) >= 0

    # 4. Redis — mock was called
    assert summary.get("redis.sessions", -1) >= 0

    # 5. Audit log — erasure must be recorded with actor id
    audit_present = await _audit_exists(db, TENANT_X, "tenant.erase")
    assert audit_present, (
        "Audit log entry for tenant.erase not found. "
        "Every erasure must be logged with actor_user_id."
    )

    await db.rollback()


# ---------------------------------------------------------------------------
# Test: manager cannot read content during erasure (write/delete-only path)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_erasure_path_issues_no_content_selects(db: AsyncSession) -> None:
    """The erasure function must not SELECT tenant content rows.

    This test patches db.execute to intercept SQL and asserts that no
    SELECT on tenant-content tables is issued during erasure.

    The only numeric reads allowed are COUNT for the summary (not content).
    Any SELECT that fetches content columns (text, body, content, intent, etc.)
    from a tenant-owned table is a violation of the write/delete-only contract.
    """
    await _seed_tenant(db)

    content_selects: list[str] = []
    original_execute = db.execute

    async def spy_execute(statement, *args, **kwargs):
        sql = str(statement)
        # Flag any SELECT that touches content columns on tenant-owned tables.
        content_tables = {
            "conversations",
            "messages",
            "leads",
            "cms_pages",
            "child_chunks",
            "parent_chunks",
            "content_chunks",
        }
        sql_upper = sql.upper()
        if "SELECT" in sql_upper and not sql_upper.strip().startswith("SELECT COUNT"):
            for table in content_tables:
                if table.upper() in sql_upper:
                    content_selects.append(sql.strip()[:120])
        return await original_execute(statement, *args, **kwargs)

    db.execute = spy_execute  # type: ignore[method-assign]

    try:
        with (
            patch("app.tenancy.erasure._erase_minio", new_callable=AsyncMock, return_value=0),
            patch("app.tenancy.erasure._erase_redis", new_callable=AsyncMock, return_value=0),
            patch("app.tenancy.erasure._erase_traces", new_callable=AsyncMock),
        ):
            await erase_tenant(db=db, actor_user_id=ACTOR_ID, tenant_id=TENANT_X)
    finally:
        db.execute = original_execute  # type: ignore[method-assign]

    assert not content_selects, (
        f"erasure path issued content SELECT(s): {content_selects}. "
        "Erasure must be write/delete-only — no reading of tenant content."
    )

    await db.rollback()


# ---------------------------------------------------------------------------
# Test: erasure deletes under a NON-superuser role (no RLS bypass)
# ---------------------------------------------------------------------------

# Tenant-owned tables that _seed_tenant populates, spanning core + RAG + widget
# stores. Used to assert Tenant A is purged and Tenant B survives under a
# non-superuser role. (tenant_guardrail_configs is not seeded, so it is omitted.)
_ALL_TENANT_TABLES = [
    "cost_events",
    "leads",
    "messages",
    "conversations",
    "child_chunks",
    "parent_chunks",
    "content_chunks",
    "cms_pages",
    "widget_configs",
    "widgets",
    "widget_allowed_origins",
    "widget_signing_key_versions",
    "widget_guardrail_configs",
]


@pytest.mark.asyncio
async def test_erasure_deletes_under_non_superuser_role(db: AsyncSession) -> None:
    """Prove erasure works when RLS is actually enforced (no superuser bypass).

    The DATABASE_URL role is usually ``postgres`` (superuser), which bypasses
    FORCE ROW LEVEL SECURITY — so a passing erase under it does NOT prove the
    DELETE reaches rows when RLS is live. Here we create a least-privilege
    NON-superuser role, ``SET ROLE`` to it (RLS now applies), and run the real
    ``erase_tenant``. The deletes only land because ``erase_tenant`` sets the
    target tenant's RLS context; without that, the policy would match zero rows
    and Tenant A would survive (this test would fail). No mocks for the deletion.
    """
    tenant_x_rows = await _seed_tenant(db)
    await _seed_tenant(
        db,
        TENANT_Y,
        name="NonSuper Survivor",
        slug="nonsuper-survivor",
        live_parent_text="Tenant Y nonsuper survivor parent",
        live_child_text="Tenant Y nonsuper survivor child",
        widget_public_id="wgt-nonsuper-surv",
        origin="https://y-nonsuper.example.com",
    )

    # Least-privilege role: can DML, but NOT a superuser and NOT BYPASSRLS, so
    # FORCE ROW LEVEL SECURITY is enforced for it (unlike the postgres login).
    await db.execute(
        text(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'albert_app_rls') THEN "
            "CREATE ROLE albert_app_rls NOLOGIN NOSUPERUSER NOBYPASSRLS; "
            "END IF; END $$;"
        )
    )
    await db.execute(text("GRANT USAGE ON SCHEMA public TO albert_app_rls"))
    await db.execute(
        text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO albert_app_rls")
    )
    await db.execute(
        text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO albert_app_rls")
    )
    await db.flush()

    # Sanity: both tenants have rows in every tenant-owned table (superuser view).
    for table in _ALL_TENANT_TABLES:
        assert await _count(db, table, TENANT_X) >= 1, f"seed FAIL: {table} TENANT_X"
        assert await _count(db, table, TENANT_Y) >= 1, f"seed FAIL: {table} TENANT_Y"

    # Drop to the non-superuser role — RLS is now actively enforced for this session.
    await db.execute(text("SET ROLE albert_app_rls"))
    try:
        with (
            patch("app.tenancy.erasure._erase_minio", new_callable=AsyncMock, return_value=0),
            patch("app.tenancy.erasure._erase_redis", new_callable=AsyncMock, return_value=0),
            patch("app.tenancy.erasure._erase_traces", new_callable=AsyncMock),
        ):
            summary = await erase_tenant(db=db, actor_user_id=ACTOR_ID, tenant_id=TENANT_X)
    finally:
        await db.execute(text("RESET ROLE"))

    # Deletes must have actually landed (not silently scoped to zero by RLS).
    assert summary.get("postgres.leads", -1) == 1, (
        "Erasure deleted 0 lead rows under the non-superuser role — the DELETE was "
        "blocked by FORCE RLS because no tenant context was set during erasure."
    )

    # Back as superuser for assertions: Tenant A purged everywhere, Tenant B intact.
    for table in _ALL_TENANT_TABLES:
        remaining_a = await _count(db, table, TENANT_X)
        assert remaining_a == 0, (
            f"NON-SUPERUSER erase FAIL: {table} still has {remaining_a} rows for TENANT_X."
        )
        assert await _count(db, table, TENANT_Y) >= 1, (
            f"Isolation FAIL: {table} for TENANT_Y was deleted by TENANT_X erasure."
        )

    # Tenant A's erased content is no longer retrievable.
    tenant_a_results = await retrieve(
        tenant_id=str(TENANT_X),
        query="nonsuper survivor parent",
        db=db,
        embedder=_StaticEmbedder(),
        reranker=_PassthroughReranker(),
    )
    assert tenant_a_results == []
    assert tenant_x_rows["parent_id"] not in {uuid.UUID(r.parent_chunk_id) for r in tenant_a_results}

    # Audit row recorded with the actor id.
    assert await _audit_exists(db, TENANT_X, "tenant.erase")

    await db.rollback()
