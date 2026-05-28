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

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import get_widget_session
from app.core.config import settings
from app.core.rate_limit import hash_identifier
from app.core.security import WidgetSessionClaims
from app.db.tenant_session import get_tenant_db
from app.schemas.widget_chat import WidgetChatRequest, WidgetChatResponse
from app.services import memory as memory_service
from app.services import router as router_service
from app.services.agent import run_agent

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])
logger = logging.getLogger(__name__)

_GUARDRAILS_TIMEOUT = 5.0


async def _guardrails_check(endpoint: str, text: str) -> bool:
    """POST to guardrails sidecar. Fails closed on any error or block."""
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
            logger.warning("widget.guardrails.%s non-200 status=%d — blocking", endpoint, resp.status_code)
            return False
        return bool(resp.json().get("allowed", False))
    except Exception as exc:
        logger.warning("widget.guardrails.%s failed error=%s — blocking (fail closed)", endpoint, exc)
        return False


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

    if not await _guardrails_check("input", payload.message):
        raise HTTPException(status_code=400, detail="Message blocked by guardrails")

    redis = request.app.state.redis
    history = await memory_service.load_history(redis, tenant_id, str(conversation_id))

    decision = await router_service.classify_and_route(payload.message, tenant_id)

    # spam label → drop immediately
    if decision.action == "direct" and decision.reply is None:
        raise HTTPException(status_code=400, detail="Message blocked")

    if decision.action == "direct" and decision.reply:
        reply = decision.reply
    else:
        tenant_db_ctx = asynccontextmanager(get_tenant_db)
        async with tenant_db_ctx(tenant_id) as db:
            result = await run_agent(
                tenant_id=tenant_id,
                conversation_id=str(conversation_id),
                user_message=payload.message,
                llm=request.app.state.llm,
                db=db,
                redis=redis,
                embedder=request.app.state.embedder,
                reranker=request.app.state.reranker,
                history=history,
            )
        reply = result.reply

    if not await _guardrails_check("output", reply):
        raise HTTPException(status_code=400, detail="Response blocked by guardrails")

    await memory_service.save_turn(redis, tenant_id, str(conversation_id), payload.message, reply)

    logger.info("widget_chat.done tenant=%s conv=%s", tenant_id, conversation_id)
    return WidgetChatResponse(
        conversation_id=conversation_id,
        message=reply,
    )
