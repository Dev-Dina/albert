"""POST /api/v1/widget/chat — visitor chat surface (US1 stub).

The assistant integration lives in Owner B's lane; this stub echoes the user
message so the round-trip path (token verify → RLS context → response) can
be exercised end-to-end in US1.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends

from app.api.deps import get_widget_session
from app.core.security import WidgetSessionClaims
from app.schemas.widget_chat import WidgetChatRequest, WidgetChatResponse

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])
logger = logging.getLogger(__name__)


@router.post("/chat", response_model=WidgetChatResponse)
async def post_widget_chat(
    payload: WidgetChatRequest,
    claims: WidgetSessionClaims = Depends(get_widget_session),
) -> WidgetChatResponse:
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
