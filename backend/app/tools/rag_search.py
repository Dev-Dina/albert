import logging

logger = logging.getLogger(__name__)

# Tool definition in the format the Groq/OpenAI API expects.
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


async def rag_search(*, tenant_id: str, query: str) -> list[dict]:
    """Search the tenant's vector store and return ranked chunks.

    retrieval_service is not yet built — returns a placeholder until Owner A
    delivers the RAG layer. Replace this body once retrieval_service exists.
    """
    logger.debug("rag_search tenant=%s query=%r", tenant_id, query)
    # TODO: replace with real call once retrieval_service is available:
    # from app.services.retrieval import retrieval_service
    # return await retrieval_service.search(tenant_id=tenant_id, query=query)
    return [
        {
            "chunk_id": "placeholder-1",
            "content": "This is a placeholder result. RAG retrieval not yet wired.",
            "score": 0.0,
        }
    ]
