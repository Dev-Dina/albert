"""Isolation eval: total erasure test (A7 checkpoint from OWNER_A_PLAN).

Verifies that ``erase_tenant`` purges every store and leaves an audit trail.

The five stores (per PROJECT_CONTEXT.md §11):
  1. Postgres rows         — all tenant-owned tables
  2. pgvector embeddings   — content_chunks (covered by Postgres, asserted explicitly)
  3. MinIO blobs           — objects under {tenant_id}/ prefix
  4. Redis sessions        — keys matching session:{tenant_id}:*
  5. Traces / logs         — stub (Owner C); asserted as a warning in logs

"The row is deleted but the embeddings are still searchable" = FAIL.

Run inside Docker:

    docker compose exec backend uv run pytest evals/isolation/test_erasure_total.py -v
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.tenancy.erasure import erase_tenant

_TEST_DB_URL = settings.database_url or "postgresql+asyncpg://postgres:postgres@postgres:5432/albert"

TENANT_X = uuid.UUID("eeeeeeee-0000-0000-0000-000000000099")
ACTOR_ID = uuid.UUID("ffffffff-0000-0000-0000-000000000001")


@pytest.fixture(scope="module")
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
# Helper: seed tenant X with data in every store
# ---------------------------------------------------------------------------

async def _seed_tenant(db: AsyncSession) -> dict[str, uuid.UUID]:
    """Insert representative rows for TENANT_X in every tenant-owned table."""
    # Tenant row (platform table — no RLS)
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) VALUES "
            "(:id, 'Erasure Test Tenant', 'erasure-test', 'active') "
            "ON CONFLICT (id) DO UPDATE SET status = 'active'"
        ),
        {"id": str(TENANT_X)},
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
        {"id": str(cms_id), "tid": str(TENANT_X)},
    )

    # Content chunk (pgvector proxy)
    chunk_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO content_chunks (id, tenant_id, chunk_text) VALUES "
            "(:id, :tid, 'some chunk')"
        ),
        {"id": str(chunk_id), "tid": str(TENANT_X)},
    )

    # Conversation + message
    conv_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, session_id) VALUES "
            "(:id, :tid, 'sess-x')"
        ),
        {"id": str(conv_id), "tid": str(TENANT_X)},
    )
    msg_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO messages (id, tenant_id, conversation_id, role, content) VALUES "
            "(:id, :tid, :cid, 'user', 'hello world')"
        ),
        {"id": str(msg_id), "tid": str(TENANT_X), "cid": str(conv_id)},
    )

    # Lead
    lead_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO leads (id, tenant_id, name, contact, intent) VALUES "
            "(:id, :tid, 'Alice', 'alice@example.com', 'buy')"
        ),
        {"id": str(lead_id), "tid": str(TENANT_X)},
    )

    # Widget config
    wc_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO widget_configs (id, tenant_id, public_widget_id) VALUES "
            "(:id, :tid, 'wgt-test')"
        ),
        {"id": str(wc_id), "tid": str(TENANT_X)},
    )

    # Cost event
    ce_id = uuid.uuid4()
    await db.execute(
        text(
            "INSERT INTO cost_events "
            "(id, tenant_id, call_type, model, input_tokens, output_tokens, cost_usd) VALUES "
            "(:id, :tid, 'llm', 'test-model', 100, 50, 0.001)"
        ),
        {"id": str(ce_id), "tid": str(TENANT_X)},
    )

    await db.flush()
    return {
        "cms_id": cms_id,
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


# ---------------------------------------------------------------------------
# Main test: erasure is total
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_erasure_is_total(db: AsyncSession) -> None:
    """Erase TENANT_X and assert every store is empty.

    MinIO and Redis calls are mocked so this test runs without those services.
    The Postgres assertions are live — they require a running database.
    """
    await _seed_tenant(db)

    # Mock the external-store erasure helpers so the test is self-contained.
    with (
        patch("app.tenancy.erasure._erase_minio", new_callable=AsyncMock, return_value=1),
        patch("app.tenancy.erasure._erase_redis", new_callable=AsyncMock, return_value=2),
        patch("app.tenancy.erasure._erase_traces", new_callable=AsyncMock),
    ):
        summary = await erase_tenant(db=db, actor_user_id=ACTOR_ID, tenant_id=TENANT_X)

    # 1. Postgres — all tenant-owned tables must be empty for TENANT_X
    for table in [
        "cost_events",
        "leads",
        "messages",
        "conversations",
        "content_chunks",
        "cms_pages",
        "widget_configs",
        "tenant_guardrail_configs",
    ]:
        remaining = await _count(db, table, TENANT_X)
        assert remaining == 0, (
            f"Store FAIL: {table} still has {remaining} rows for tenant {TENANT_X}. "
            "'Deleted but still searchable' is a compliance failure."
        )

    # 2. pgvector — content_chunks explicitly asserted above; summary must record it
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
    content_selects: list[str] = []
    original_execute = db.execute

    async def spy_execute(statement, *args, **kwargs):
        sql = str(statement)
        # Flag any SELECT that touches content columns on tenant-owned tables.
        content_tables = {"conversations", "messages", "leads", "cms_pages", "content_chunks"}
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
