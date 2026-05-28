"""POST /api/v1/widget/chat — visitor chat surface (US1 stub).

The assistant integration lives in Owner B's lane; this stub echoes the user
message so the round-trip path (token verify → RLS context → response) can
be exercised end-to-end. US2 (T048) adds the "body tenant_id is ignored AND
logged" check: a hostile body field never reaches the handler's tenant
context (which comes from the token claims), and an operator-visible log line
is emitted when one is seen. Per FR-015c the foreign tenant id is hashed
before logging so logs cannot leak it.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_widget_session
from app.core.rate_limit import hash_identifier
from app.core.security import WidgetSessionClaims
from app.schemas.widget_chat import WidgetChatRequest, WidgetChatResponse

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])
logger = logging.getLogger(__name__)


async def _peek_for_foreign_tenant_id(request: Request) -> str | None:
    """Return a hashed foreign tenant id if the raw body carries one.

    Starlette caches ``request.body()`` on first access, so downstream FastAPI
    parsing of ``WidgetChatRequest`` sees the same bytes — calling this here
    does not consume the body for the route.
    """
    try:
        import json

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

    # OWNER C AUDIT NOTE (Owner B integration — not implemented here): this echo
    # stub must be replaced with the real path: token tenant -> classifier/router
    # -> agent/RAG/tools -> guardrails OUTPUT check -> response. The Owner C
    # guardrails sidecar is ready at POST /guardrails/input and /guardrails/output
    # (Authorization: Bearer <SERVICE_AUTH_TOKEN>, fail closed on error/non-200).
    conversation_id = payload.conversation_id or uuid.uuid4()
    logger.info(
        "widget_chat",
        extra={
            "event": "widget_chat",
            "widget_id": str(claims.widget_id),
            "conversation_id": str(conversation_id),
        },
    )
    return WidgetChatResponse(
        conversation_id=conversation_id,
        message=f"You said: {payload.message}",
    )
