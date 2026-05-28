import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_admin_tenant_id
from app.core.config import settings
from app.db.tenant_session import get_tenant_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import memory as memory_service
from app.services import router as router_service
from app.services.agent import run_agent

logger = logging.getLogger(__name__)

router = APIRouter()

_GUARDRAILS_TIMEOUT = 5.0


async def _guardrails_check(endpoint: str, text: str) -> bool:
    """POST to guardrails sidecar. Returns True only when sidecar explicitly allows.

    Fails closed: any non-200, timeout, connection error, or block verdict → False.
    """
    try:
        async with httpx.AsyncClient(timeout=_GUARDRAILS_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.guardrails_url}/{endpoint}",
                json={"text": text},
                headers={
                    "Authorization": f"Bearer {settings.service_auth_token.get_secret_value()}"
                },
            )
        if resp.status_code != 200:
            logger.warning("guardrails.%s non-200 status=%d — blocking", endpoint, resp.status_code)
            return False
        data = resp.json()
        allowed: bool = data.get("allowed", False)
        if not allowed:
            logger.info("guardrails.%s blocked", endpoint)
        return allowed
    except Exception as exc:
        logger.warning("guardrails.%s failed error=%s — blocking (fail closed)", endpoint, exc)
        return False


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

    if not await _guardrails_check("input", body.message):
        raise HTTPException(status_code=400, detail="Message blocked by guardrails")

    decision = await router_service.classify_and_route(body.message, tenant_id)

    # spam label → drop immediately, no agent call
    if decision.action == "direct" and decision.reply is None:
        raise HTTPException(status_code=400, detail="Message blocked")

    if decision.action == "direct" and decision.reply:
        reply = decision.reply
        routed_to = "router"
    else:
        tenant_db_ctx = asynccontextmanager(get_tenant_db)
        async with tenant_db_ctx(tenant_id) as db:
            result = await run_agent(
                tenant_id=tenant_id,
                conversation_id=body.conversation_id,
                user_message=body.message,
                llm=request.app.state.llm,
                db=db,
                redis=redis,
                embedder=request.app.state.embedder,
                reranker=request.app.state.reranker,
                history=history,
            )
        reply = result.reply
        routed_to = "agent"

    if not await _guardrails_check("output", reply):
        raise HTTPException(status_code=400, detail="Response blocked by guardrails")

    await memory_service.save_turn(redis, tenant_id, body.conversation_id, body.message, reply)

    logger.info("chat.done tenant=%s conv=%s routed_to=%s", tenant_id, body.conversation_id, routed_to)
    return ChatResponse(reply=reply, routed_to=routed_to)
