import json
import logging

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import settings
from app.core.secrets import get_secret_value

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """The upstream LLM provider failed (404/unavailable/quota/auth, etc.).

    Raised at the adapter boundary so callers can return a controlled 5xx
    instead of leaking a raw provider stack trace. Carries no prompt text,
    API key, or other sensitive content.
    """


class LLMAdapter:
    """Thin async wrapper over the Gemini LLM API.

    Mounted on app.state.llm during lifespan so a single client is reused
    across all requests. tenant_id is attached to every call for cost
    attribution logging — never used for routing or isolation logic.
    """

    def __init__(self, client: genai.Client, model: str) -> None:
        self._client = client
        self._model = model

    async def chat(
        self,
        *,
        tenant_id: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> object:
        """Call the Gemini chat endpoint and return a response object.

        Converts the OpenAI-style messages list to Gemini's Content format,
        then wraps the response back into a choices[0]-style object so the
        agent loop doesn't need to change.
        """
        resolved_model = model or self._model
        resolved_max_tokens = max_tokens or settings.agent_max_tokens_per_turn
        logger.debug("llm.chat tenant=%s model=%s", tenant_id, resolved_model)

        # Separate system prompt from conversation turns.
        system_instruction = None
        contents: list[types.Content] = []
        for msg in messages:
            role = msg.get("role")
            if role == "system":
                system_instruction = msg.get("content", "")
                continue
            if role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=msg.get("content", ""))]))
            elif role == "assistant":
                parts = []
                if msg.get("content"):
                    parts.append(types.Part(text=msg["content"]))
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        parts.append(types.Part(function_call=types.FunctionCall(
                            name=tc["function"]["name"],
                            args=json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"],
                        )))
                contents.append(types.Content(role="model", parts=parts))
            elif role == "tool":
                contents.append(types.Content(role="user", parts=[types.Part(
                    function_response=types.FunctionResponse(
                        name=msg.get("name", "tool"),
                        response={"result": msg.get("content", "")},
                    )
                )]))

        gemini_tools = None
        if tools:
            declarations = []
            for t in tools:
                fn = t["function"]
                declarations.append(types.FunctionDeclaration(
                    name=fn["name"],
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters"),
                ))
            gemini_tools = [types.Tool(function_declarations=declarations)]

        config = types.GenerateContentConfig(
            max_output_tokens=resolved_max_tokens,
            system_instruction=system_instruction,
            tools=gemini_tools,
        )

        try:
            response = await self._client.aio.models.generate_content(
                model=resolved_model,
                contents=contents,
                config=config,
            )
        except genai_errors.APIError as exc:
            # Provider 4xx/5xx (e.g. model 404, quota, auth). Log only the model
            # and status code — never the prompt, contents, key, or full message.
            logger.warning(
                "llm.provider_error tenant=%s model=%s code=%s",
                tenant_id,
                resolved_model,
                getattr(exc, "code", "unknown"),
            )
            raise LLMProviderError(
                f"LLM provider error (model={resolved_model}, code={getattr(exc, 'code', 'unknown')})"
            ) from exc

        return _GeminiResponseWrapper(response)


class _GeminiUsage:
    """Token counts extracted from Gemini usage_metadata."""

    def __init__(self, response: object) -> None:
        meta = getattr(response, "usage_metadata", None)
        self.prompt_tokens: int = getattr(meta, "prompt_token_count", 0) or 0
        self.completion_tokens: int = getattr(meta, "candidates_token_count", 0) or 0


class _GeminiResponseWrapper:
    """Wraps a Gemini response to expose the choices[0] interface the agent loop expects."""

    def __init__(self, response: object) -> None:
        self._response = response
        self.choices = [_GeminiChoiceWrapper(response)]
        self.usage = _GeminiUsage(response)


class _GeminiChoiceWrapper:
    """Wraps a Gemini candidate to expose finish_reason and message."""

    def __init__(self, response: object) -> None:
        self._response = response
        candidate = response.candidates[0] if response.candidates else None
        self.message = _GeminiMessageWrapper(candidate)

        # Map Gemini finish reasons to OpenAI-style strings.
        if candidate is None:
            self.finish_reason = "stop"
            return

        has_fn = any(
            hasattr(p, "function_call") and p.function_call is not None
            for p in (candidate.content.parts if candidate.content else [])
        )
        self.finish_reason = "tool_calls" if has_fn else "stop"


class _GeminiMessageWrapper:
    """Wraps a Gemini candidate content to expose content, tool_calls, and model_dump()."""

    def __init__(self, candidate: object) -> None:
        self._candidate = candidate
        self.content: str = ""
        self.tool_calls: list | None = None

        if candidate is None or not candidate.content:
            return

        text_parts = []
        fn_calls = []
        for part in candidate.content.parts:
            if hasattr(part, "function_call") and part.function_call is not None:
                fn_calls.append(_GeminiFunctionCallWrapper(part.function_call))
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        self.content = "".join(text_parts)
        self.tool_calls = fn_calls if fn_calls else None

    def model_dump(self) -> dict:
        result: dict = {"role": "assistant", "content": self.content or None, "tool_calls": None}
        if self.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in self.tool_calls
            ]
        return result


class _GeminiFunctionCallWrapper:
    """Wraps a Gemini FunctionCall to expose .id and .function.name/.arguments."""

    def __init__(self, fn_call: object) -> None:
        self.id = f"call_{fn_call.name}"
        self.function = _GeminiFunctionWrapper(fn_call)


class _GeminiFunctionWrapper:
    def __init__(self, fn_call: object) -> None:
        self.name: str = fn_call.name
        self.arguments: str = json.dumps(dict(fn_call.args) if fn_call.args else {})


async def build_llm_adapter() -> LLMAdapter:
    """Construct the adapter from settings. Called once in lifespan.

    Vault is the source of truth for the API key. The config value is a
    local-dev fallback only — never put a real key in config or .env.
    """
    api_key = await get_secret_value(
        "gemini_api_key",
        fallback=settings.gemini_api_key.get_secret_value(),
    )
    client = genai.Client(api_key=api_key)
    return LLMAdapter(client=client, model=settings.gemini_model)
