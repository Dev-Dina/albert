import logging

from groq import AsyncGroq

from app.core.config import settings
from app.core.secrets import get_secret_value

logger = logging.getLogger(__name__)


class LLMAdapter:
    """Thin async wrapper over the Groq LLM API.

    Mounted on app.state.llm during lifespan so a single client is reused
    across all requests. tenant_id is attached to every call for cost
    attribution logging — never used for routing or isolation logic.
    """

    def __init__(self, client: AsyncGroq) -> None:
        self._client = client

    async def chat(
        self,
        *,
        tenant_id: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> object:
        """Call the Groq chat completions endpoint and return the raw response."""
        resolved_model = model or settings.groq_model
        resolved_max_tokens = max_tokens or settings.agent_max_tokens_per_turn
        logger.debug("llm.chat tenant=%s model=%s", tenant_id, resolved_model)
        kwargs: dict = {
            "model": resolved_model,
            "messages": messages,
            "max_tokens": resolved_max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        return await self._client.chat.completions.create(**kwargs)


async def build_llm_adapter() -> LLMAdapter:
    """Construct the adapter from settings. Called once in lifespan.

    Vault is the source of truth for the API key. The config value is a
    local-dev fallback only — never put a real key in config or .env.
    """
    api_key = await get_secret_value(
        "groq_api_key",
        fallback=settings.groq_api_key.get_secret_value(),
    )
    client = AsyncGroq(api_key=api_key, timeout=30.0)
    return LLMAdapter(client)
