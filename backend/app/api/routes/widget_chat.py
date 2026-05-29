"""POST /api/v1/widget/chat — visitor chat surface.

Secure path: widget token → tenant identity → guardrails input check →
router/classifier → agent/RAG/tools → guardrails output check → response.
Tenant identity comes exclusively from the verified token claims; any
tenant_id in the request body is silently ignored and logged.
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.embedder import EmbedError
from app.adapters.llm import LLMProviderError
from app.api.deps import get_widget_session
from app.clients import inference_client
from app.core.rate_limit import hash_identifier
from app.core.security import WidgetSessionClaims
from app.db.tenant_session import get_tenant_db
from app.schemas.widget_chat import WidgetChatRequest, WidgetChatResponse
from app.services import memory as memory_service
from app.services import router as router_service
from app.services import workflow
from app.services.agent import run_agent
from app.services.conversation import ensure_conversation
from app.services.tenant_runtime import load_runtime_config

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])
logger = logging.getLogger(__name__)

# Correct guardrails routes (/check-input, /check-output) come from
# inference_client — one source of truth for the route names, service-auth
# header, and X-Request-ID propagation (prevents the /input//output 404 regress).
_GUARDRAILS_CALLS = {
    "input": inference_client.call_guardrails_check_input,
    "output": inference_client.call_guardrails_check_output,
}


async def _guardrails_check(
    endpoint: str, text: str, tenant_rails: dict | None = None
) -> bool:
    """Call the guardrails sidecar via the shared service client.

    Forwards the tenant's rails so tenant-configured blocks are enforced; the
    sidecar always evaluates platform rules first, so tenant rails can only add
    restrictions, never weaken the platform floor. Fails closed: any transport
    error, non-200, or block verdict → False.
    """
    payload: dict = {"text": text}
    if tenant_rails:
        payload["context"] = {"source": endpoint, "tenant_rails": tenant_rails}
    try:
        resp = await _GUARDRAILS_CALLS[endpoint](payload)
    except Exception as exc:
        logger.warning("widget.guardrails.%s failed error=%s — blocking (fail closed)", endpoint, exc)
        return False
    if resp.status_code != 200:
        logger.warning("widget.guardrails.%s non-200 status=%d — blocking", endpoint, resp.status_code)
        return False
    return bool(resp.json().get("allowed", False))


async def _peek_for_foreign_tenant_id(request: Request) -> str | None:
    """Return a hashed foreign tenant id if the raw body carries one."""
    try:
        raw = await request.body()
        if not raw:
            return None
        parsed = json.loads(raw)
    except (ValueError, json.JSONDecodeError):
        return None
    if not isinstance(parsed, dict):
        return None
    tenant_id = parsed.get("tenant_id")
    if not isinstance(tenant_id, str):
        return None
    return hash_identifier(tenant_id)


@router.post("/chat", response_model=WidgetChatResponse)
async def post_widget_chat(
    request: Request,
    payload: WidgetChatRequest,
    claims: WidgetSessionClaims = Depends(get_widget_session),
) -> WidgetChatResponse:
    foreign_hash = await _peek_for_foreign_tenant_id(request)
    if foreign_hash is not None:
        logger.warning(
            "body_tenant_id_ignored",
            extra={
                "event": "body_tenant_id_ignored",
                "token_tenant_id_hash": hash_identifier(str(claims.tenant_id)),
                "body_tenant_id_hash": foreign_hash,
            },
        )

    # Tenant identity from verified token only — never from the request body.
    tenant_id = str(claims.tenant_id)
    conversation_id = payload.conversation_id or uuid.uuid4()

    logger.info(
        "widget_chat.start",
        extra={
            "event": "widget_chat",
            "widget_id": str(claims.widget_id),
            "conversation_id": str(conversation_id),
        },
    )

    tenant_db_ctx = asynccontextmanager(get_tenant_db)

    # Load tenant runtime config (persona/business_name + tenant rails) under RLS.
    async with tenant_db_ctx(tenant_id) as cfg_db:
        runtime = await load_runtime_config(cfg_db, claims.tenant_id, claims.widget_id)

    if not await _guardrails_check("input", payload.message, runtime.tenant_rails):
        raise HTTPException(status_code=400, detail="Message blocked by guardrails")

    redis = request.app.state.redis
    history = await memory_service.load_history(redis, tenant_id, str(conversation_id))

    decision = await router_service.classify_and_route(payload.message, tenant_id)

    # Cheap workflow paths handle enumerable easy cases without the agent;
    # reply=None means fall back to the bounded agent. The RAG path embeds the
    # query, so a provider embedding failure becomes a controlled 503, not a 500.
    try:
        wf = await workflow.dispatch(
            decision,
            message=payload.message,
            tenant_id=tenant_id,
            conversation_id=str(conversation_id),
            db_ctx=tenant_db_ctx,
            redis=redis,
            embedder=request.app.state.embedder,
            reranker=request.app.state.reranker,
        )
    except EmbedError:
        logger.warning("widget_chat.embed_unavailable conversation_id=%s", str(conversation_id))
        raise HTTPException(
            status_code=503, detail="Knowledge retrieval is temporarily unavailable"
        ) from None

    if wf.dropped:
        raise HTTPException(status_code=400, detail="Message blocked")

    agent_called = False
    if wf.reply is not None:
        reply = wf.reply
        handled_by = wf.handled_by
    else:
        agent_called = True
        handled_by = "agent"
        try:
            async with tenant_db_ctx(tenant_id) as db:
                # Ensure the conversations row exists (same TX) so the agent's
                # cost-event insert satisfies the cost_events.conversation_id FK.
                await ensure_conversation(db, claims.tenant_id, conversation_id)
                result = await run_agent(
                    tenant_id=tenant_id,
                    conversation_id=str(conversation_id),
                    user_message=payload.message,
                    llm=request.app.state.llm,
                    db=db,
                    redis=redis,
                    embedder=request.app.state.embedder,
                    reranker=request.app.state.reranker,
                    persona=runtime.persona,
                    business_name=runtime.business_name,
                    history=history,
                )
                # Persist the conversation + cost events for this turn.
                await db.commit()
        except LLMProviderError:
            # Controlled 503 instead of a raw 500 / provider stack trace.
            logger.warning("widget_chat.llm_unavailable conversation_id=%s", str(conversation_id))
            raise HTTPException(
                status_code=503, detail="AI service temporarily unavailable"
            ) from None
        except EmbedError:
            logger.warning("widget_chat.embed_unavailable conversation_id=%s", str(conversation_id))
            raise HTTPException(
                status_code=503, detail="Knowledge retrieval is temporarily unavailable"
            ) from None
        reply = result.reply

    # Backstop: an empty reply (e.g. a degenerate LLM "stop" with no text) would
    # fail the guardrails output check's min_length=1 validation and surface as a
    # hard 400. Substitute a safe, non-empty fallback so the visitor gets a
    # graceful message instead of an error.
    if not reply or not reply.strip():
        logger.warning(
            "widget_chat.empty_reply conversation_id=%s — using fallback",
            str(conversation_id),
        )
        reply = "Sorry, I wasn't able to put together a response just then. Could you try rephrasing your question?"

    if not await _guardrails_check("output", reply, runtime.tenant_rails):
        raise HTTPException(status_code=400, detail="Response blocked by guardrails")

    await memory_service.save_turn(redis, tenant_id, str(conversation_id), payload.message, reply)

    logger.info(
        "widget_chat.done",
        extra={
            "event": "widget_chat_done",
            "route_label": decision.label,
            "handled_by": handled_by,
            "agent_called": agent_called,
        },
    )
    return WidgetChatResponse(
        conversation_id=conversation_id,
        message=reply,
    )
