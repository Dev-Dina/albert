import logging

import cohere

from app.core.secrets import get_secret_value

logger = logging.getLogger(__name__)


class RerankerAdapter:
    """Calls Cohere Rerank API to re-score (query, chunk) pairs.

    Mounted on app.state.reranker during lifespan.
    Falls back to original order if the API call fails.
    """

    def __init__(self, client: cohere.AsyncClientV2) -> None:
        self._client = client

    async def rerank(self, query: str, texts: list[str]) -> list[tuple[int, float]]:
        """Rerank texts against query. Returns list of (original_index, score) sorted by score desc.

        Falls back to [(i, 0.0) for i in range(len(texts))] on API error.
        """
        if not texts:
            return []
        try:
            response = await self._client.rerank(
                model="rerank-v3.5",
                query=query,
                documents=texts,
                return_documents=False,
            )
            return [(r.index, r.relevance_score) for r in response.results]
        except Exception as exc:
            logger.warning("reranker.rerank failed, using original order: %s", exc)
            return [(i, 0.0) for i in range(len(texts))]


async def build_reranker_adapter() -> RerankerAdapter:
    """Construct the adapter from settings. Called once in lifespan."""
    api_key = await get_secret_value("cohere_api_key", fallback=None)
    client = cohere.AsyncClientV2(api_key=api_key or "dev-cohere-key-change-me")
    return RerankerAdapter(client=client)
