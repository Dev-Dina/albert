import logging

from pydantic import BaseModel, field_validator

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
    *, tenant_id: str, conversation_id: str, reason: str, summary: str = ""
) -> dict:
    """Flag the conversation for human handoff, scoped to tenant_id.

    Writes to conversation_flags table — stub until Owner A delivers
    the Conversation model and get_current_tenant dependency.

    tenant_id and conversation_id come from verified session context.
    """
    logger.info(
        "escalate tenant=%s conv=%s reason=%r", tenant_id, conversation_id, reason
    )

    EscalateArgs(reason=reason, summary=summary)

    # TODO: replace with real repo write once Owner A delivers Conversation model:
    # from app.repos.conversation_repo import conversation_repo
    # flag = await conversation_repo.flag_for_escalation(
    #     tenant_id=tenant_id,
    #     conversation_id=conversation_id,
    #     reason=args.reason,
    #     summary=args.summary,
    # )
    # return {"ticket_id": str(flag.id), "status": "escalated"}

    # OWNER C AUDIT NOTE (Owner A/B integration — not implemented here): the
    # conversations table exists (migration 0003). This must persist a tenant-scoped
    # escalation/flag (tenant_id + conversation_id from verified context), OR be
    # explicitly marked out of scope for the submission. It currently writes nothing.
    logger.warning("escalate is a stub — no DB write performed tenant=%s", tenant_id)
    return {"ticket_id": None, "status": "stub_no_write"}
