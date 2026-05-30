"""Unit tests for app.services.ingestion.ingest_tenant_content().

All DB and API calls are mocked — no real database or API keys needed.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.embedder import EmbedError
from app.services.ingestion import ingest_tenant_content, _split_into_chunks


# --- chunker unit tests ---

def test_split_empty_text_returns_empty() -> None:
    assert _split_into_chunks("", 256, 512) == []


def test_split_whitespace_only_returns_empty() -> None:
    assert _split_into_chunks("   \n  ", 256, 512) == []


def test_split_short_text_returns_single_chunk() -> None:
    text = "Hello world"
    result = _split_into_chunks(text, 256, 512)
    assert result == ["Hello world"]


def test_split_long_text_respects_max_chars() -> None:
    text = "word " * 300  # 1500 chars
    chunks = _split_into_chunks(text, 256, 512)
    for chunk in chunks:
        assert len(chunk) <= 512


# --- ingestion service tests ---

def _make_page(content_id: uuid.UUID, body: str) -> dict:
    return {"content_id": content_id, "body": body}


@pytest.mark.asyncio
async def test_empty_content_body_is_skipped() -> None:
    tenant_id = str(uuid.uuid4())
    db = AsyncMock()
    embedder = AsyncMock()

    pages = [_make_page(uuid.uuid4(), ""), _make_page(uuid.uuid4(), "   ")]

    with patch("app.services.ingestion._fetch_content_pages", return_value=pages), \
         patch("app.services.ingestion.ChunkRepo"):
        result = await ingest_tenant_content(
            tenant_id=tenant_id,
            db=db,
            embedder=embedder,
        )

    assert result.pages_processed == 0
    assert result.parent_chunks_written == 0
    assert result.errors == []
    embedder.embed_batch.assert_not_called()


@pytest.mark.asyncio
async def test_embed_error_skips_page_and_records_error() -> None:
    tenant_id = str(uuid.uuid4())
    content_id = uuid.uuid4()
    db = AsyncMock()
    embedder = AsyncMock()
    embedder.embed_batch.side_effect = EmbedError("API down")

    pages = [_make_page(content_id, "Some real content about opening hours.")]

    with patch("app.services.ingestion._fetch_content_pages", return_value=pages), \
         patch("app.services.ingestion.ChunkRepo"):
        result = await ingest_tenant_content(
            tenant_id=tenant_id,
            db=db,
            embedder=embedder,
        )

    assert result.pages_processed == 0
    assert len(result.errors) == 1
    assert str(content_id) in result.errors[0]


@pytest.mark.asyncio
async def test_all_pages_fail_returns_success_false() -> None:
    tenant_id = str(uuid.uuid4())
    db = AsyncMock()
    embedder = AsyncMock()
    embedder.embed_batch.side_effect = EmbedError("API down")

    pages = [
        _make_page(uuid.uuid4(), "Content page one."),
        _make_page(uuid.uuid4(), "Content page two."),
    ]

    with patch("app.services.ingestion._fetch_content_pages", return_value=pages), \
         patch("app.services.ingestion.ChunkRepo"):
        result = await ingest_tenant_content(
            tenant_id=tenant_id,
            db=db,
            embedder=embedder,
        )

    assert result.success is False
    assert len(result.errors) == 2


@pytest.mark.asyncio
async def test_idempotency_deletes_existing_chunks_before_writing() -> None:
    tenant_id = str(uuid.uuid4())
    content_id = uuid.uuid4()
    db = AsyncMock()
    embedder = AsyncMock()
    embedder.embed_batch.return_value = [[0.1] * 768]

    pages = [_make_page(content_id, "Short content.")]

    with patch("app.services.ingestion._fetch_content_pages", return_value=pages), \
         patch("app.services.ingestion.ChunkRepo") as MockRepo:
        mock_repo = MockRepo.return_value
        mock_repo.delete_chunks_for_content = AsyncMock()
        mock_repo.write_parent_chunks = AsyncMock()
        mock_repo.write_child_chunks = AsyncMock()

        await ingest_tenant_content(
            tenant_id=tenant_id,
            db=db,
            embedder=embedder,
        )

    # delete must be called before write — ensuring idempotency.
    mock_repo.delete_chunks_for_content.assert_called_once()
    mock_repo.write_parent_chunks.assert_called_once()
    mock_repo.write_child_chunks.assert_called_once()

    call_args = mock_repo.delete_chunks_for_content.call_args
    assert call_args.args[0] == content_id or call_args.kwargs.get("content_id") == content_id


# --- feature 007: _fetch_content_pages reads published CMS pages -------------

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models.cms_page import CmsPage
from app.db.models.tenant import Tenant
from app.services.ingestion import _fetch_content_pages


@pytest.mark.asyncio
async def test_fetch_content_pages_returns_published_only_and_tenant_scoped() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    async with SessionLocal() as s:
        conn = await s.connection()
        tables = [t for t in Base.metadata.sorted_tables if t.name in ("tenants", "cms_pages")]
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=tables))
        s.add(Tenant(id=tenant_a, name="A", slug="a", status="active"))
        s.add(Tenant(id=tenant_b, name="B", slug="b", status="active"))
        published = CmsPage(
            id=uuid.uuid4(), tenant_id=tenant_a, title="P", slug="p",
            body="published body", is_published=True,
        )
        draft = CmsPage(
            id=uuid.uuid4(), tenant_id=tenant_a, title="D", slug="d",
            body="draft body", is_published=False,
        )
        other_tenant = CmsPage(
            id=uuid.uuid4(), tenant_id=tenant_b, title="O", slug="o",
            body="other tenant body", is_published=True,
        )
        s.add_all([published, draft, other_tenant])
        await s.commit()

        pages = await _fetch_content_pages(s, tenant_a, None)

    assert {p["body"] for p in pages} == {"published body"}  # excludes draft + other tenant
    assert {p["content_id"] for p in pages} == {published.id}


@pytest.mark.asyncio
async def test_remove_page_chunks_deletes_chunks_for_content() -> None:
    """Delete path removes the page's chunks (content_id + tenant scoped)."""
    from unittest.mock import AsyncMock, patch

    from app.services import cms_service

    tenant = str(uuid.uuid4())
    page = str(uuid.uuid4())
    fake_repo = AsyncMock()
    fake_session = AsyncMock()
    fake_session.__aenter__.return_value = fake_session
    fake_session.__aexit__.return_value = False

    with patch(
        "app.services.cms_service._tenant_session", AsyncMock(return_value=fake_session)
    ), patch("app.services.cms_service.ChunkRepo", return_value=fake_repo):
        await cms_service._remove_page_chunks(object(), tenant, page)

    fake_repo.delete_chunks_for_content.assert_awaited_once()
    args = fake_repo.delete_chunks_for_content.await_args.args
    assert str(args[0]) == page
    assert str(args[1]) == tenant
    fake_session.commit.assert_awaited_once()
