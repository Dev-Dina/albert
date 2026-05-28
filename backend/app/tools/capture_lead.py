import logging
import uuid

from pydantic import BaseModel, field_validator
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models.lead import Lead

logger = logging.getLogger(__name__)

_MAX_LEADS_PER_CONVERSATION = 3

# Tool definition in the format the Groq/OpenAI API expects.
# tenant_id is NOT in this schema — the backend injects it from the verified token.
CAPTURE_LEAD_TOOL: dict = {
    "type": "function",
    "function": {
        "name": "capture_lead",
        "description": (
            "Save a visitor's contact details when they express interest. "
            "Only call this when the visitor has explicitly provided their name and contact."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The visitor's full name.",
                },
                "contact": {
                    "type": "string",
                    "description": "The visitor's email address or phone number.",
                },
                "intent": {
                    "type": "string",
                    "description": "Short description of what the visitor is interested in.",
                },
            },
            "required": ["name", "contact", "intent"],
        },
    },
}


class CaptureLeadArgs(BaseModel):
    name: str
    contact: str
    intent: str

    @field_validator("name", "intent")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        if len(v) > 500:
            raise ValueError("too long")
        return v.strip()

    @field_validator("contact")
    @classmethod
    def contact_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        if len(v) > 255:
            raise ValueError("too long")
        return v.strip()


async def capture_lead(
    *,
    tenant_id: str,
    name: str,
    contact: str,
    intent: str,
    db: AsyncSession | None = None,
    redis: Redis | None = None,
    conversation_id: str | None = None,
) -> dict:
    """Write a lead record scoped to tenant_id.

    Rate-limited to _MAX_LEADS_PER_CONVERSATION writes per conversation via Redis
    to prevent prompt-injection spam cannon attacks.
    tenant_id comes from verified session context — never from the LLM output.
    """
    logger.debug("capture_lead tenant=%s contact=%r", tenant_id, contact)

    CaptureLeadArgs(name=name, contact=contact, intent=intent)

    if redis is not None and conversation_id is not None:
        rate_key = f"lead_rate:{tenant_id}:{conversation_id}"
        try:
            count = await redis.incr(rate_key)
            if count == 1:
                await redis.expire(rate_key, settings.redis_session_ttl)
            if count > _MAX_LEADS_PER_CONVERSATION:
                logger.warning(
                    "capture_lead.rate_limited tenant=%s conv=%s count=%d",
                    tenant_id, conversation_id, count,
                )
                return {"lead_id": None, "status": "rate_limited"}
        except Exception:
            logger.warning("capture_lead.rate_check_failed tenant=%s — allowing write", tenant_id)

    if db is None:
        logger.warning("capture_lead called without db session — skipping write tenant=%s", tenant_id)
        return {"lead_id": None, "status": "no_db"}

    lead = Lead(
        id=uuid.uuid4(),
        tenant_id=uuid.UUID(tenant_id),
        name=name,
        contact=contact,
        intent=intent,
        status="new",
    )
    db.add(lead)
    await db.flush()
    logger.info("capture_lead.persisted tenant=%s lead_id=%s", tenant_id, lead.id)
    return {"lead_id": str(lead.id), "status": "captured"}
