import logging
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedder import EmbedderAdapter, EmbedError
from app.adapters.reranker import RerankerAdapter
from app.repos.chunk_repo import ChunkRepo

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    parent_chunk_id: str
    text: str
    score: float
    source_content_id: str


async def retrieve(
    *,
    tenant_id: str,
    query: str,
    top_k: int = 5,
    candidate_k: int = 20,
    db: AsyncSession,
    embedder: EmbedderAdapter,
    reranker: RerankerAdapter,
) -> list[RetrievalResult]:
    """Embed query → ANN search children → rerank → deduplicate to parents → return top_k.

    - Raises ValueError if query is empty.
    - Raises EmbedError if the embedding API call fails.
    - Falls back to similarity order if reranker fails (handled inside RerankerAdapter).
    - Returns [] if no chunks exist for the tenant.
    - NEVER returns chunks from a different tenant.
    """
    if not query or not query.strip():
        raise ValueError("query must not be empty")

    repo = ChunkRepo(db)

    # Embed the query — raises EmbedError on API failure.
    query_embedding = await embedder.embed_one(query)

    # ANN search over child_chunks scoped to this tenant.
    children = await repo.search_children(
        embedding=query_embedding,
        tenant_id=uuid.UUID(tenant_id),
        top_k=candidate_k,
    )

    if not children:
        return []

    child_texts = [c.text for c in children]

    # Rerank — falls back to original order internally on failure.
    ranked = await reranker.rerank(query=query, texts=child_texts)

    # Sort by reranker score descending, then deduplicate to unique parent_ids.
    ranked_sorted = sorted(ranked, key=lambda x: x[1], reverse=True)
    seen_parents: list[uuid.UUID] = []
    score_by_parent: dict[uuid.UUID, float] = {}
    for orig_idx, score in ranked_sorted:
        parent_id = children[orig_idx].parent_id
        if parent_id not in score_by_parent:
            seen_parents.append(parent_id)
            score_by_parent[parent_id] = score
        if len(seen_parents) >= top_k:
            break

    # Fetch parent chunk texts — scoped to tenant_id.
    parents = await repo.fetch_parents_by_ids(
        parent_ids=seen_parents,
        tenant_id=uuid.UUID(tenant_id),
    )

    return [
        RetrievalResult(
            parent_chunk_id=str(p.id),
            text=p.text,
            score=score_by_parent.get(p.id, 0.0),
            source_content_id=str(p.content_id),
        )
        for p in parents
    ]
