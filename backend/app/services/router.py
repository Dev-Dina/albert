import logging

import httpx

from app.core.config import settings
from app.schemas.router import RouterDecision

logger = logging.getLogger(__name__)

_DIRECT_REPLIES: dict[str, str] = {
    "greeting": "Hello! How can I help you today?",
    "farewell": "Thank you for chatting! Goodbye.",
    "out_of_scope": "I'm only able to help with questions about this business.",
}


async def classify_and_route(message: str, tenant_id: str) -> RouterDecision:
    """Classify message via model-server and return a routing decision.

    Falls back to action='agent' on any HTTP error or low confidence.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            # OWNER C AUDIT NOTE (Owner B integration — not changed here):
            # modelserver POST /classify expects {"text": <message>}
            # (ClassifyRequest, extra="forbid"), NOT {"message": ...}. The current
            # body 422s, so the except-branch below silently falls back to the agent
            # on every call. Classifier labels are: faq_rag, lead_capture,
            # human_escalate, spam, other_agent (not greeting/farewell/out_of_scope).
            resp = await client.post(
                f"{settings.modelserver_url}/classify",
                json={"message": message},
                headers={
                    "Authorization": f"Bearer {settings.service_auth_token.get_secret_value()}"
                },
            )
            resp.raise_for_status()
            data = resp.json()
            label: str = data.get("label", "ambiguous")
            confidence: float = float(data.get("confidence", 0.0))
    except Exception as exc:
        logger.warning("router.classify_failed tenant=%s error=%s — falling back to agent", tenant_id, exc)
        return RouterDecision(action="agent", label="unknown", confidence=0.0, routed_to="agent")

    if confidence < settings.router_confidence_threshold or label == "ambiguous":
        logger.info("router.low_confidence tenant=%s label=%s conf=%.2f — agent", tenant_id, label, confidence)
        return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent")

    if label in _DIRECT_REPLIES:
        logger.info("router.direct tenant=%s label=%s", tenant_id, label)
        # Stub: increment router_handled counter (swap with Owner A's cost tracker)
        logger.info("router.counter tenant=%s counter=router_handled", tenant_id)
        return RouterDecision(
            action="direct",
            label=label,
            confidence=confidence,
            routed_to="router",
            reply=_DIRECT_REPLIES[label],
        )

    logger.info("router.agent_handoff tenant=%s label=%s", tenant_id, label)
    # Stub: increment agent_handled counter
    logger.info("router.counter tenant=%s counter=agent_handled", tenant_id)
    return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent")
