from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

IntentLabel = Literal[
    "faq_rag",
    "lead_capture",
    "human_escalate",
    "spam",
    "other_agent",
]


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=4000)


class ClassifyResponse(BaseModel):
    label: IntentLabel
    confidence: float = Field(..., ge=0.0, le=1.0)
    model_version: str
    artifact_sha256: str
    threshold_applied: bool
    predicted_label: IntentLabel
    predicted_confidence: float = Field(..., ge=0.0, le=1.0)
