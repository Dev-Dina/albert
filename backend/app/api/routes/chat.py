import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, Request

from app.adapters.llm import LLMProviderError
from app.api.deps import get_admin_tenant_id
from app.clients import inference_client
from app.db.tenant_session import get_tenant_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import memory as memory_service
from app.services import router as router_service
from app.services import workflow
from app.services.agent import run_agent
from app.services.conversation import ensure_conversation
from app.services.tenant_runtime import load_runtime_config

logger = logging.getLogger(__name__)

router = APIRouter()

# The correct guardrails routes (/check-input, /check-output) live in
# inference_client. Routing through it keeps the service-auth header and
# X-Request-ID propagation in one place and prevents per-route URL drift —
# e.g. the historical /input//output 404 that failed every chat closed.
_GUARDRAILS_CALLS = {
    "input": inference_client.call_guardrails_check_input,
    "output": inference_client.call_guardrails_check_output,
}


async def _guardrails_check(
    endpoint: str, text: str, tenant_rails: dict | None = None
) -> bool:
    """Call the guardrails sidecar via the shared service client.

    Forwards the tenant's rails (tenant blocks are additive; the sidecar applies
    platform rules first, so the floor cannot be weakened). Returns True only
    when the sidecar explicitly allows. Fails closed: any transport error,
    non-200, or block verdict → False.
    """
    payload: dict = {"text": text}
    if tenant_rails:
        payload["context"] = {"source": endpoint, "tenant_rails": tenant_rails}
    try:
        resp = await _GUARDRAILS_CALLS[endpoint](payload)
    except Exception as exc:
        logger.warning("guardrails.%s failed error=%s — blocking (fail closed)", endpoint, exc)
        return False
    if resp.status_code != 200:
        logger.warning("guardrails.%s non-200 status=%d — blocking", endpoint, resp.status_code)
        return False
    allowed: bool = resp.json().get("allowed", False)
    if not allowed:
        logger.info("guardrails.%s blocked", endpoint)
    return allowed


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    tenant_id: str = Depends(get_admin_tenant_id),
) -> ChatResponse:

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    redis = request.app.state.redis

    history = await memory_service.load_history(redis, tenant_id, body.conversation_id)

    tenant_db_ctx = asynccontextmanager(get_tenant_db)

    # Load tenant runtime config (business_name + tenant rails) under RLS. The
    # authed chat surface has no widget, so persona stays the platform default.
    async with tenant_db_ctx(tenant_id) as cfg_db:
        runtime = await load_runtime_config(cfg_db, uuid.UUID(tenant_id))

    if not await _guardrails_check("input", body.message, runtime.tenant_rails):
        raise HTTPException(status_code=400, detail="Message blocked by guardrails")

    decision = await router_service.classify_and_route(body.message, tenant_id)

    # Cheap workflow paths handle enumerable easy cases without the agent;
    # reply=None means fall back to the bounded agent.
    wf = await workflow.dispatch(
        decision,
        message=body.message,
        tenant_id=tenant_id,
        conversation_id=body.conversation_id,
        db_ctx=tenant_db_ctx,
        redis=redis,
        embedder=request.app.state.embedder,
        reranker=request.app.state.reranker,
    )

    if wf.dropped:
        raise HTTPException(status_code=400, detail="Message blocked")

    agent_called = False
    if wf.reply is not None:
        reply = wf.reply
        routed_to = wf.handled_by
    else:
        agent_called = True
        routed_to = "agent"
        try:
            async with tenant_db_ctx(tenant_id) as db:
                # Ensure the conversations row exists (same TX) so the agent's
                # cost-event insert satisfies the cost_events.conversation_id FK.
                try:
                    conv_uuid = uuid.UUID(body.conversation_id)
                except ValueError:
                    conv_uuid = None
                if conv_uuid is not None:
                    await ensure_conversation(db, uuid.UUID(tenant_id), conv_uuid)
                result = await run_agent(
                    tenant_id=tenant_id,
                    conversation_id=body.conversation_id,
                    user_message=body.message,
                    llm=request.app.state.llm,
                    db=db,
                    redis=redis,
                    embedder=request.app.state.embedder,
                    reranker=request.app.state.reranker,
                    business_name=runtime.business_name,
                    history=history,
                )
                await db.commit()
        except LLMProviderError:
            logger.warning("chat.llm_unavailable conversation_id=%s", body.conversation_id)
            raise HTTPException(
                status_code=503, detail="AI service temporarily unavailable"
            ) from None
        reply = result.reply

    if not await _guardrails_check("output", reply, runtime.tenant_rails):
        raise HTTPException(status_code=400, detail="Response blocked by guardrails")

    await memory_service.save_turn(redis, tenant_id, body.conversation_id, body.message, reply)

    logger.info(
        "chat.done tenant=%s conv=%s route_label=%s handled_by=%s agent_called=%s",
        tenant_id, body.conversation_id, decision.label, routed_to, agent_called,
    )
    return ChatResponse(reply=reply, routed_to=routed_to)
