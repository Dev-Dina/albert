import json
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.embedder import EmbedderAdapter
from app.adapters.llm import LLMAdapter
from app.adapters.reranker import RerankerAdapter
from app.core.config import settings
from app.cost import record_cost_event
from app.tools.capture_lead import CAPTURE_LEAD_TOOL, capture_lead
from app.tools.escalate import ESCALATE_TOOL, escalate
from app.tools.rag_search import RAG_SEARCH_TOOL, rag_search

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Full tool list passed to the LLM on every turn — registered at one explicit line.
TOOL_LIST: list[dict] = [
    RAG_SEARCH_TOOL,
    CAPTURE_LEAD_TOOL,
    ESCALATE_TOOL,
]


@dataclass
class AgentResult:
    reply: str
    escalated: bool = False
    iterations_used: int = 0
    tool_calls: list[str] = field(default_factory=list)


async def run_agent(
    *,
    tenant_id: str,
    conversation_id: str,
    user_message: str,
    llm: LLMAdapter,
    db: AsyncSession | None = None,
    redis: Redis | None = None,
    embedder: EmbedderAdapter | None = None,
    reranker: RerankerAdapter | None = None,
    persona: str = "Albert",
    business_name: str = "the business",
    history: list[dict] | None = None,
) -> AgentResult:
    """Run the bounded agent loop for one user turn.

    Exits when the model returns a plain text reply, all tools are exhausted,
    or max_iterations is reached (auto-escalates in that case).
    """
    jinja_env = Environment(loader=FileSystemLoader(str(_PROMPTS_DIR)), autoescape=False)
    system_prompt = jinja_env.get_template("system_prompt.j2").render(
        persona=persona,
        business_name=business_name,
        max_iterations=settings.agent_max_iterations,
    )

    messages: list[dict] = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    iterations = 0
    tool_calls_made: list[str] = []

    while iterations < settings.agent_max_iterations:
        iterations += 1
        logger.info(
            "agent.turn tenant=%s conv=%s iter=%d",
            tenant_id,
            conversation_id,
            iterations,
        )

        response = await llm.chat(
            tenant_id=tenant_id,
            messages=messages,
            tools=TOOL_LIST,
            max_tokens=settings.agent_max_tokens_per_turn,
        )

        if db is not None:
            try:
                await record_cost_event(
                    db=db,
                    tenant_id=uuid.UUID(tenant_id),
                    call_type="llm",
                    model=settings.gemini_model,
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
                )
            except Exception:
                logger.warning("agent.cost_record_failed tenant=%s", tenant_id)

        choice = response.choices[0]

        # Model returned a plain text reply — done.
        if choice.finish_reason == "stop":
            return AgentResult(
                reply=choice.message.content or "",
                escalated=False,
                iterations_used=iterations,
                tool_calls=tool_calls_made,
            )

        # Model wants to call tools.
        if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
            messages.append(choice.message.model_dump())

            for tc in choice.message.tool_calls:
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments)
                tool_calls_made.append(tool_name)

                logger.info(
                    "agent.tool_call tenant=%s tool=%s", tenant_id, tool_name
                )

                result = await _dispatch_tool(
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tenant_id=tenant_id,
                    conversation_id=conversation_id,
                    db=db,
                    redis=redis,
                    embedder=embedder,
                    reranker=reranker,
                )

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps(result),
                    }
                )
            continue

        # Unexpected finish reason — break and escalate.
        logger.warning(
            "agent.unexpected_finish tenant=%s reason=%s",
            tenant_id,
            choice.finish_reason,
        )
        break

    # Max iterations reached or unexpected finish — auto-escalate.
    logger.warning(
        "agent.escalating tenant=%s conv=%s after %d iterations",
        tenant_id,
        conversation_id,
        iterations,
    )
    return AgentResult(
        reply="I've reached the limit of what I can help with right now. Let me connect you with a team member.",
        escalated=True,
        iterations_used=iterations,
        tool_calls=tool_calls_made,
    )


async def _dispatch_tool(
    *,
    tool_name: str,
    tool_args: dict,
    tenant_id: str,
    conversation_id: str | None = None,
    db: AsyncSession | None = None,
    redis: Redis | None = None,
    embedder: EmbedderAdapter | None = None,
    reranker: RerankerAdapter | None = None,
) -> object:
    """Route a tool call to the correct handler."""
    if tool_name == "rag_search":
        if db is None or embedder is None or reranker is None:
            logger.warning("rag_search called without db/embedder/reranker — returning empty")
            return []
        return await rag_search(
            tenant_id=tenant_id,
            query=tool_args["query"],
            db=db,
            embedder=embedder,
            reranker=reranker,
        )

    if tool_name == "capture_lead":
        return await capture_lead(
            tenant_id=tenant_id,
            db=db,
            redis=redis,
            conversation_id=conversation_id,
            **tool_args,
        )

    if tool_name == "escalate":
        # tenant_id + conversation_id come from trusted server context, NEVER the
        # LLM tool args (the model only supplies a human-readable reason/summary).
        # Using tool_args here was the bug that sent conversation_id="unknown".
        return await escalate(
            tenant_id=tenant_id,
            conversation_id=conversation_id or "",
            reason=tool_args.get("reason") or "Visitor requested human assistance.",
            summary=tool_args.get("summary", ""),
            db=db,
        )

    logger.error("agent.unknown_tool tool=%s", tool_name)
    return {"error": f"Unknown tool: {tool_name}"}
