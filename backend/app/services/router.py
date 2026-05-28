import logging

import httpx

from app.core.config import settings
from app.schemas.router import RouterDecision

logger = logging.getLogger(__name__)

# Canonical labels from the model server (Owner C).
# spam → drop immediately; faq_rag → RAG; lead_capture / human_escalate / other_agent → agent.
_SPAM_LABELS = {"spam"}
_AGENT_LABELS = {"faq_rag", "lead_capture", "human_escalate", "other_agent"}


async def classify_and_route(message: str, tenant_id: str) -> RouterDecision:
    """Classify message via model-server and return a routing decision.

    Falls back to action='agent' on any HTTP error or low confidence.
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
        return RouterDecision(action="agent", label="unknown", confidence=0.0, routed_to="agent")

    if confidence < settings.router_confidence_threshold or label == "ambiguous":
        logger.info("router.low_confidence tenant=%s label=%s conf=%.2f — agent", tenant_id, label, confidence)
        return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent")

    if label in _SPAM_LABELS:
        logger.info("router.spam_drop tenant=%s label=%s", tenant_id, label)
        return RouterDecision(action="direct", label=label, confidence=confidence, routed_to="router", reply=None)

    if label in _AGENT_LABELS:
        logger.info("router.agent_handoff tenant=%s label=%s", tenant_id, label)
        return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent")

    # Unknown label — safe fallback to agent.
    logger.info("router.unknown_label tenant=%s label=%s — agent", tenant_id, label)
    return RouterDecision(action="agent", label=label, confidence=confidence, routed_to="agent")
