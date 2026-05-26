import logging

import httpx

from app.core.config import settings
from app.core.secrets import get_secret_value

logger = logging.getLogger(__name__)

_GEMINI_EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:embedContent?key={api_key}"
)
_GEMINI_BATCH_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models"
    "/{model}:batchEmbedContents?key={api_key}"
)


class EmbedError(Exception):
    """Raised when the embedding API call fails."""


class EmbedderAdapter:
    """Calls Gemini text-embedding-004 to produce 768-dim vectors.

    Mounted on app.state.embedder during lifespan.
    All calls are async; no local model weights required.
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single string. Used at query time."""
        url = _GEMINI_EMBED_URL.format(model=self._model, api_key=self._api_key)
        payload = {"model": f"models/{self._model}", "content": {"parts": [{"text": text}]}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("embedder.embed_one failed: %s", exc)
                raise EmbedError(str(exc)) from exc
        return resp.json()["embedding"]["values"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Used during ingestion (batches of ≤100)."""
        url = _GEMINI_BATCH_URL.format(model=self._model, api_key=self._api_key)
        requests = [
            {"model": f"models/{self._model}", "content": {"parts": [{"text": t}]}}
            for t in texts
        ]
        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                resp = await client.post(url, json={"requests": requests})
                resp.raise_for_status()
            except httpx.HTTPError as exc:
                logger.error("embedder.embed_batch failed: %s", exc)
                raise EmbedError(str(exc)) from exc
        return [item["values"] for item in resp.json()["embeddings"]]


async def build_embedder_adapter() -> EmbedderAdapter:
    """Construct the adapter from settings. Called once in lifespan."""
    api_key = await get_secret_value(
        "gemini_api_key",
        fallback=settings.gemini_api_key.get_secret_value(),
    )
    return EmbedderAdapter(api_key=api_key, model=settings.gemini_embedding_model)
