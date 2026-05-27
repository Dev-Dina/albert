from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Action = Literal["allow", "block", "redact"]
Decision = Literal["allow", "deny"]


class TenantRails(BaseModel):
    model_config = ConfigDict(extra="ignore")

    allowed_topics: list[str] = Field(default_factory=list)
    blocked_topics: list[str] = Field(default_factory=list)
    enabled_tools: list[str] = Field(default_factory=list)
    tone: str | None = None


class GuardrailContext(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source: Literal["input", "output"] | None = None
    request_id: str | None = None
    tenant_id: str | None = None
    tenant_rails: TenantRails | None = None


class GuardrailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1, max_length=8000)
    context: GuardrailContext | None = None


class RedactionSummary(BaseModel):
    total: int
    counts: dict[str, int] = Field(default_factory=dict)


class GuardrailResponse(BaseModel):
    allowed: bool
    action: Action
    decision: Decision
    reason_code: str
    message: str
    refusal: str | None = None
    triggered_rules: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    redacted_text: str | None = None
    redaction_summary: RedactionSummary | None = None
    platform_blocked: bool = False
    tenant_policy_applied: bool = False
    reason: str
