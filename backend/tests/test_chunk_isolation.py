"""Tenant isolation test for retrieval.

Mocks two tenant IDs, runs retrieve() for Tenant A, and verifies that
the retrieval service passes Tenant A's ID into the repository layer.

This test mocks the DB layer — RLS enforcement is tested separately.
Here we verify that retrieval does not accidentally call the repository
with the wrong tenant_id.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.retrieval import retrieve


@pytest.mark.asyncio
async def test_retrieval_never_returns_other_tenant_chunks() -> None:
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    parent_id_a = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
    parent_id_b = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")
    content_id = uuid.uuid4()

    db = AsyncMock()

    embedder = AsyncMock()
    embedder.embed_one.return_value = [0.1] * 768

    reranker = AsyncMock()
    reranker.rerank.return_value = [(0, 0.9)]

    child_a = MagicMock()
    child_a.parent_id = parent_id_a
    child_a.text = "Tenant A content"

    parent_a = MagicMock()
    parent_a.id = parent_id_a
    parent_a.tenant_id = uuid.UUID(tenant_a)
    parent_a.content_id = content_id
    parent_a.text = "Tenant A full text"

    with patch("app.services.retrieval.ChunkRepo") as MockRepo:
        mock_repo = MockRepo.return_value
        mock_repo.search_children = AsyncMock(return_value=[child_a])
        mock_repo.fetch_parents_by_ids = AsyncMock(return_value=[parent_a])

        result = await retrieve(
            tenant_id=tenant_a,
            query="some question",
            db=db,
            embedder=embedder,
            reranker=reranker,
        )

    assert len(result) == 1
    assert result[0].parent_chunk_id == str(parent_id_a)

    search_kwargs = mock_repo.search_children.call_args.kwargs
    assert str(search_kwargs["tenant_id"]) == tenant_a
    assert str(search_kwargs["tenant_id"]) != tenant_b

    fetch_kwargs = mock_repo.fetch_parents_by_ids.call_args.kwargs
    assert str(fetch_kwargs["tenant_id"]) == tenant_a
    assert str(fetch_kwargs["tenant_id"]) != tenant_b

    result_ids = {r.parent_chunk_id for r in result}
    assert str(parent_id_a) in result_ids
    assert str(parent_id_b) not in result_ids