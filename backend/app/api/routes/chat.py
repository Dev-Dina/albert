import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Header, HTTPException, Request

from app.db.tenant_session import get_tenant_db
from app.schemas.chat import ChatRequest, ChatResponse
from app.services import memory as memory_service
from app.services import router as router_service
from app.services.agent import run_agent

logger = logging.getLogger(__name__)

router = APIRouter()


def _guardrails_check(text: str) -> bool:
    # OWNER C AUDIT NOTE (Owner B integration — not implemented here): the Owner C
    # guardrails sidecar is delivered. This must call it before agent input AND
    # after final output via POST /guardrails/input and /guardrails/output, with
    # Authorization: Bearer <SERVICE_AUTH_TOKEN>, and FAIL CLOSED on error/non-200.
    return True


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> ChatResponse:
    # OWNER C AUDIT NOTE (Owner A/B — not changed here): tenant identity must come
    # from the verified widget/session token, never a client-supplied X-Tenant-Id
    # header. Trusting this header is a cross-tenant breach vector.
    tenant_id = x_tenant_id

    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")

    redis = request.app.state.redis

    history = await memory_service.load_history(redis, tenant_id, body.conversation_id)

    if not _guardrails_check(body.message):
        raise HTTPException(status_code=400, detail="Message blocked by guardrails")

    decision = await router_service.classify_and_route(body.message, tenant_id)

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
                embedder=request.app.state.embedder,
                reranker=request.app.state.reranker,
                history=history,
            )
        reply = result.reply
        routed_to = "agent"

    if not _guardrails_check(reply):
        reply = "I'm sorry, I can't help with that."

    await memory_service.save_turn(redis, tenant_id, body.conversation_id, body.message, reply)

    logger.info("chat.done tenant=%s conv=%s routed_to=%s", tenant_id, body.conversation_id, routed_to)
    return ChatResponse(reply=reply, routed_to=routed_to)
