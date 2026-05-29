import logging

import httpx

from app.core.config import settings
from app.schemas.router import Handler, RouterDecision

logger = logging.getLogger(__name__)

# Canonical labels from the model server (Owner C) → cheap-path handler.
# Enumerable easy cases are handled by the workflow; only genuinely
# ambiguous/open-ended turns (other_agent, low confidence) go to the agent.
_LABEL_HANDLER: dict[str, Handler] = {
    "spam": "drop",
    "faq_rag": "rag",
    "lead_capture": "lead",
    "human_escalate": "escalate",
    "other_agent": "agent",
}


def handler_for_label(label: str) -> Handler:
    """Pure label→handler mapping (also used by the routing cost report)."""
    return _LABEL_HANDLER.get(label, "agent")


async def classify_and_route(message: str, tenant_id: str) -> RouterDecision:
    """Classify the message via model-server and return a routing decision.

    Falls back to the agent on any HTTP error, low confidence, or ambiguous label.
    """
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.post(
                f"{settings.modelserver_url}/classify",
                json={"text": message},
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
        return RouterDecision(action="agent", label="unknown", confidence=0.0, routed_to="agent", handler="agent")

    if confidence < settings.router_confidence_threshold or label == "ambiguous":
        logger.info("router.low_confidence tenant=%s label=%s conf=%.2f — agent", tenant_id, label, confidence)
        return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent", handler="agent")

    handler = handler_for_label(label)

    if handler == "drop":
        logger.info("router.spam_drop tenant=%s label=%s", tenant_id, label)
        return RouterDecision(action="direct", label=label, confidence=confidence, routed_to="router", reply=None, handler="drop")

    if handler == "agent":
        logger.info("router.agent_handoff tenant=%s label=%s", tenant_id, label)
        return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent", handler="agent")

    # Cheap workflow paths: rag / lead / escalate — no agent call.
    logger.info("router.workflow tenant=%s label=%s handler=%s", tenant_id, label, handler)
    return RouterDecision(action="direct", label=label, confidence=confidence, routed_to="workflow", handler=handler)
