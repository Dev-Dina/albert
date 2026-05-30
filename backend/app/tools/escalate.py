import logging
import uuid

from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation

logger = logging.getLogger(__name__)

# Tool definition in the format the Groq/OpenAI API expects.
# tenant_id and conversation_id are NOT in this schema — backend injects them.
ESCALATE_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "escalate",
        "description": (
            "Hand the conversation off to a human agent. Call this when the visitor "
            "explicitly asks for a person, or when the issue is outside your scope."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why escalation is needed.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short context summary for the human agent (optional).",
                },
            },
            "required": ["reason"],
        },
    },
}


class EscalateArgs(BaseModel):
    reason: str
    summary: str = ""

    @field_validator("reason")
    @classmethod
    def reason_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        if len(v) > 1000:
            raise ValueError("too long")
        return v.strip()

    @field_validator("summary")
    @classmethod
    def summary_bounded(cls, v: str) -> str:
        if len(v) > 2000:
            raise ValueError("too long")
        return v.strip()


async def escalate(
    *, tenant_id: str, conversation_id: str, reason: str, summary: str = "", db: AsyncSession | None = None
) -> dict:
    """Flag the conversation for human handoff, scoped to tenant_id.

    Sets conversation status to 'escalated'. tenant_id and conversation_id
    come from verified session context — never from client input.
    """
    # Log ids only — the escalation reason/summary are tenant free-text and are
    # persisted to the escalations table, not the application log (Principle III).
    logger.info(
        "escalate tenant=%s conv=%s reason_len=%d",
        tenant_id, conversation_id, len(reason or ""),
    )

    EscalateArgs(reason=reason, summary=summary)

    if db is None:
        logger.warning("escalate called without db session — skipping write tenant=%s", tenant_id)
        return {"ticket_id": None, "status": "no_db"}

    try:
        conv_uuid = uuid.UUID(conversation_id)
        tenant_uuid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.warning("escalate invalid uuid tenant=%s conv=%s", tenant_id, conversation_id)
        return {"ticket_id": None, "status": "invalid_id"}

    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_uuid,
            Conversation.tenant_id == tenant_uuid,
        )
    )
    conv = result.scalar_one_or_none()
    if conv is None:
        # No existing conversation row — create one marked escalated.
        conv = Conversation(
            id=conv_uuid,
            tenant_id=tenant_uuid,
            session_id=conversation_id,
            status="escalated",
        )
        db.add(conv)
    else:
        conv.status = "escalated"

    await db.flush()

    # Persist the escalation context (1:1 per conversation, upsert). The reason
    # was already validated above; summary may be empty (FR-033). This runs on
    # the same chat-session DB, whose app.current_tenant RLS GUC is already set
    # (the path that writes conversations/messages) — tenant_id/conversation_id
    # come only from the verified session context, never from the LLM.
    from app.repositories import escalation_repo

    await escalation_repo.upsert(
        db,
        tenant_id=tenant_uuid,
        conversation_id=conv_uuid,
        reason=reason.strip(),
        summary=summary.strip(),
    )

    logger.info("escalate.persisted tenant=%s conv=%s", tenant_id, conversation_id)
    return {"ticket_id": conversation_id, "status": "escalated"}
