import logging

from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)

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


async def capture_lead(*, tenant_id: str, name: str, contact: str, intent: str) -> dict:
    """Write a lead record scoped to tenant_id.

    Rate-limiting and the real DB write are stubs until Owner A delivers
    the Lead model and get_current_tenant dependency.

    tenant_id comes from verified session context — never from the LLM output.
    """
    logger.debug("capture_lead tenant=%s contact=%r", tenant_id, contact)

    CaptureLeadArgs(name=name, contact=contact, intent=intent)

    # TODO: rate-limit check per visitor/session before writing
    # if await _rate_limit_exceeded(tenant_id=tenant_id):
    #     return {"status": "rate_limited", "lead_id": None}

    # TODO: replace with real repo write once Owner A delivers Lead model:
    # from app.repos.lead_repo import lead_repo
    # lead = await lead_repo.create(
    #     tenant_id=tenant_id,
    #     name=args.name,
    #     contact=args.contact,
    #     intent=args.intent,
    # )
    # return {"lead_id": str(lead.id), "status": "captured"}

    # OWNER C AUDIT NOTE (Owner A/B integration — not implemented here): the Lead
    # model + leads table now exist (app.db.models.lead, migration 0003). This must
    # persist a tenant-scoped lead (tenant_id from verified context, never LLM
    # output) with per-visitor/session write rate-limiting, OR be explicitly marked
    # out of scope for the submission. It currently writes nothing.
    logger.warning("capture_lead is a stub — no DB write performed tenant=%s", tenant_id)
    return {"lead_id": None, "status": "stub_no_write"}
