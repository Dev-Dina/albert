import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.core.secrets import get_secret_value

logger = logging.getLogger(__name__)


class EmbedError(Exception):
    """Raised when the embedding API call fails.

    Carries only the model name + provider status code — never the API key,
    request URL, prompt text, or a chained provider traceback (which can embed
    a ``?key=`` query string). Callers translate this into a controlled 5xx.
    """


class EmbedderAdapter:
    """Produces query/document embeddings via the hosted Gemini embeddings API.

    Uses the ``google-genai`` SDK (same client style as the LLM adapter) so the
    API key travels in a request header, never in a logged URL. Output
    dimensionality is pinned to match the pgvector column; no local model weights.
    """

    def __init__(self, client: genai.Client, model: str, dimensions: int) -> None:
        self._client = client
        self._model = model
        self._dimensions = dimensions

    def _config(self, task_type: str) -> types.EmbedContentConfig:
        return types.EmbedContentConfig(
            task_type=task_type,
            output_dimensionality=self._dimensions,
        )

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single query string. Used at retrieval time."""
        try:
            resp = await self._client.aio.models.embed_content(
                model=self._model,
                contents=text,
                config=self._config("RETRIEVAL_QUERY"),
            )
        except genai_errors.APIError as exc:
            logger.warning(
                "embedder.embed_one provider_error model=%s code=%s",
                self._model, getattr(exc, "code", "unknown"),
            )
            raise EmbedError(
                f"embedding provider error (model={self._model}, code={getattr(exc, 'code', 'unknown')})"
            ) from None
        except Exception as exc:
            logger.warning("embedder.embed_one failed model=%s err=%s", self._model, type(exc).__name__)
            raise EmbedError(f"embedding call failed (model={self._model})") from None
        return list(resp.embeddings[0].values)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents. Used during ingestion / RAG seeding."""
        try:
            resp = await self._client.aio.models.embed_content(
                model=self._model,
                contents=texts,
                config=self._config("RETRIEVAL_DOCUMENT"),
            )
        except genai_errors.APIError as exc:
            logger.warning(
                "embedder.embed_batch provider_error model=%s code=%s",
                self._model, getattr(exc, "code", "unknown"),
            )
            raise EmbedError(
                f"embedding provider error (model={self._model}, code={getattr(exc, 'code', 'unknown')})"
            ) from None
        except Exception as exc:
            logger.warning("embedder.embed_batch failed model=%s err=%s", self._model, type(exc).__name__)
            raise EmbedError(f"embedding call failed (model={self._model})") from None
        return [list(e.values) for e in resp.embeddings]


async def build_embedder_adapter() -> EmbedderAdapter:
    """Construct the adapter from settings. Called once in lifespan.

    Vault is the source of truth for the API key; the config value is a local-dev
    fallback only. Model + dimensionality are config-driven (dimensions must match
    the ``child_chunks.embedding`` pgvector column).
    """
    api_key = await get_secret_value(
        "gemini_api_key",
        fallback=settings.gemini_api_key.get_secret_value(),
    )
    client = genai.Client(api_key=api_key)
    return EmbedderAdapter(
        client=client,
        model=settings.gemini_embedding_model,
        dimensions=settings.gemini_embedding_dimensions,
    )
