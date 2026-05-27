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
    # TODO: call guardrails service when Owner C delivers it
    return True


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    body: ChatRequest,
    x_tenant_id: str = Header(..., alias="X-Tenant-Id"),
) -> ChatResponse:
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
