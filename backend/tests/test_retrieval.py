"""Unit tests for app.services.retrieval.retrieve().

All DB and API calls are mocked — no real database or API keys needed.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.embedder import EmbedError
from app.services.retrieval import RetrievalResult, retrieve


def _make_child(parent_id: uuid.UUID, text: str = "child text") -> MagicMock:
    c = MagicMock()
    c.parent_id = parent_id
    c.text = text
    return c


def _make_parent(parent_id: uuid.UUID, content_id: uuid.UUID, text: str = "parent text") -> MagicMock:
    p = MagicMock()
    p.id = parent_id
    p.content_id = content_id
    p.text = text
    return p


@pytest.mark.asyncio
async def test_empty_query_raises_value_error() -> None:
    db = AsyncMock()
    embedder = AsyncMock()
    reranker = AsyncMock()
    with pytest.raises(ValueError, match="empty"):
        await retrieve(
            tenant_id=str(uuid.uuid4()),
            query="",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )


@pytest.mark.asyncio
async def test_whitespace_query_raises_value_error() -> None:
    db = AsyncMock()
    embedder = AsyncMock()
    reranker = AsyncMock()
    with pytest.raises(ValueError):
        await retrieve(
            tenant_id=str(uuid.uuid4()),
            query="   ",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )


@pytest.mark.asyncio
async def test_embed_error_propagates() -> None:
    db = AsyncMock()
    embedder = AsyncMock()
    embedder.embed_one.side_effect = EmbedError("API down")
    reranker = AsyncMock()

    with pytest.raises(EmbedError):
        await retrieve(
            tenant_id=str(uuid.uuid4()),
            query="test query",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )


@pytest.mark.asyncio
async def test_no_children_returns_empty_list() -> None:
    tenant_id = str(uuid.uuid4())
    db = AsyncMock()
    embedder = AsyncMock()
    embedder.embed_one.return_value = [0.1] * 768
    reranker = AsyncMock()

    with patch("app.services.retrieval.ChunkRepo") as MockRepo:
        mock_repo = MockRepo.return_value
        mock_repo.search_children = AsyncMock(return_value=[])
        result = await retrieve(
            tenant_id=tenant_id,
            query="what are your hours?",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )

    assert result == []


@pytest.mark.asyncio
async def test_reranker_error_falls_back_to_similarity_order() -> None:
    tenant_id = str(uuid.uuid4())
    parent_id = uuid.uuid4()
    content_id = uuid.uuid4()
    db = AsyncMock()

    embedder = AsyncMock()
    embedder.embed_one.return_value = [0.1] * 768

    reranker = AsyncMock()
    # RerankerAdapter falls back internally — simulate it returning original order with 0.0 score
    reranker.rerank.return_value = [(0, 0.0)]

    child = _make_child(parent_id)
    parent = _make_parent(parent_id, content_id, "Return policy: 30 days.")

    with patch("app.services.retrieval.ChunkRepo") as MockRepo:
        mock_repo = MockRepo.return_value
        mock_repo.search_children = AsyncMock(return_value=[child])
        mock_repo.fetch_parents_by_ids = AsyncMock(return_value=[parent])

        result = await retrieve(
            tenant_id=tenant_id,
            query="return policy",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )

    assert len(result) == 1
    assert result[0].text == "Return policy: 30 days."
    assert result[0].score == 0.0


@pytest.mark.asyncio
async def test_normal_path_returns_ordered_results() -> None:
    tenant_id = str(uuid.uuid4())
    parent_id_a = uuid.uuid4()
    parent_id_b = uuid.uuid4()
    content_id = uuid.uuid4()
    db = AsyncMock()

    embedder = AsyncMock()
    embedder.embed_one.return_value = [0.1] * 768

    # Reranker scores: child 1 (parent_b) higher than child 0 (parent_a)
    reranker = AsyncMock()
    reranker.rerank.return_value = [(1, 0.95), (0, 0.60)]

    child_a = _make_child(parent_id_a, "opening hours info")
    child_b = _make_child(parent_id_b, "return policy info")
    parent_a = _make_parent(parent_id_a, content_id, "Full opening hours text.")
    parent_b = _make_parent(parent_id_b, content_id, "Full return policy text.")

    with patch("app.services.retrieval.ChunkRepo") as MockRepo:
        mock_repo = MockRepo.return_value
        mock_repo.search_children = AsyncMock(return_value=[child_a, child_b])
        mock_repo.fetch_parents_by_ids = AsyncMock(return_value=[parent_b, parent_a])

        result = await retrieve(
            tenant_id=tenant_id,
            query="return policy",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )

    assert len(result) == 2
    assert result[0].text == "Full return policy text."
    assert result[0].score == 0.95
    assert result[1].text == "Full opening hours text."
    assert result[1].score == 0.60
