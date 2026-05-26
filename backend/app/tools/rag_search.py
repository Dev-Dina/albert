import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedder import EmbedderAdapter
from app.adapters.reranker import RerankerAdapter
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)

RAG_SEARCH_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "rag_search",
        "description": (
            "Search the tenant's knowledge base for information relevant to the "
            "visitor's question. Always call this before answering factual questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query derived from the visitor's message.",
                }
            },
            "required": ["query"],
        },
    },
}


async def rag_search(
    *,
    tenant_id: str,
    query: str,
    db: AsyncSession,
    embedder: EmbedderAdapter,
    reranker: RerankerAdapter,
) -> list[dict]:
    """Search the tenant's vector store and return ranked parent chunks."""
    logger.debug("rag_search tenant=%s query=%r", tenant_id, query)
    results = await retrieve(
        tenant_id=tenant_id,
        query=query,
        db=db,
        embedder=embedder,
        reranker=reranker,
    )
    return [
        {
            "chunk_id": r.parent_chunk_id,
            "content": r.text,
            "score": r.score,
        }
        for r in results
    ]
