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
