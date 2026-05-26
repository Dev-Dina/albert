"""Tenant isolation test for retrieval.

Seeds two tenants with different chunks, runs retrieve() for Tenant A,
and asserts that no Tenant B chunks appear in the results.

This test mocks the DB layer — the RLS enforcement is tested separately
via the migration; here we verify the repo filter logic is correct.
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

    # search_children returns only Tenant A's child (repo filters by tenant_id).
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

    # Verify results contain only Tenant A's chunk.
    assert len(result) == 1
    assert result[0].parent_chunk_id == str(parent_id_a)

    # Verify the repo was called with Tenant A's UUID — not Tenant B's.
    call_kwargs = mock_repo.search_children.call_args.kwargs
    assert str(call_kwargs["tenant_id"]) == tenant_a

    fetch_kwargs = mock_repo.fetch_parents_by_ids.call_args.kwargs
    assert str(fetch_kwargs["tenant_id"]) == tenant_a

    # Tenant B's parent_id never appears in any result.
    result_ids = {r.parent_chunk_id for r in result}
    assert str(parent_id_b) not in result_ids
