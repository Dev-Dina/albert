from __future__ import annotations

import re
from dataclasses import dataclass

from app.redaction import redact
from app.schemas import GuardrailRequest, GuardrailResponse, RedactionSummary

_SAFE_ALLOW_REASON = "guardrails_allow"
_SAFE_REDACT_REASON = "guardrails_redact"
_SAFE_BLOCK_REASON = "guardrails_block"


@dataclass(frozen=True)
class Rule:
    category: str
    reason_code: str
    pattern: re.Pattern[str]


_PLATFORM_BLOCK_RULES: tuple[Rule, ...] = (
    Rule(
        "prompt_injection",
        "prompt_injection",
        re.compile(
            r"(?i)\b(ignore|override|bypass|disable|forget)\b.{0,80}"
            r"\b(previous|prior|above|system|developer|guardrail|policy|instruction)s?\b"
        ),
    ),
    Rule(
        "jailbreak",
        "jailbreak",
        re.compile(
            r"(?i)\b(jailbreak|do anything now|dan mode|developer mode|unrestricted mode|"
            r"no restrictions|bypass safety)\b"
        ),
    ),
    Rule(
        "system_prompt_extraction",
        "system_prompt_extraction",
        re.compile(
            r"(?i)\b(show|reveal|print|dump|repeat|exfiltrate|extract)\b.{0,80}"
            r"\b(system prompt|developer prompt|internal instruction|hidden instruction|policy)\b"
        ),
    ),
    Rule(
        "cross_tenant",
        "cross_tenant",
        re.compile(
            r"(?i)\b(other|another|different)\s+tenant\b|"
            r"\btenant\s+[a-z0-9_-]+\b.{0,80}\b(data|conversation|lead|cms|secret|content)\b|"
            r"\bcross[- ]tenant\b"
        ),
    ),
    Rule(
        "tenant_id_override",
        "tenant_id_override",
        re.compile(
            r"(?i)\btenant[_-]?id\b\s*[:=]|"
            r"\bset\b.{0,40}\btenant[_-]?id\b|"
            r"\boverride\b.{0,40}\btenant\b"
        ),
    ),
    Rule(
        "tool_abuse",
        "tool_abuse",
        re.compile(
            r"(?i)\b(force|call|invoke|run|execute)\b.{0,80}"
            r"\b(rag_search|capture_lead|escalate)\b|"
            r"\buse\b.{0,40}\btool\b.{0,80}\b(other tenant|different tenant|without validation)\b"
        ),
    ),
    Rule(
        "secret",
        "secret_extraction",
        re.compile(
            r"(?i)\b(reveal|show|print|dump|return|exfiltrate|extract)\b.{0,80}"
            r"\b(api key|apikey|service token|authorization header|bearer token|cookie|secret|password)\b"
        ),
    ),
)


def evaluate_input(payload: GuardrailRequest) -> GuardrailResponse:
    return _evaluate(payload, surface="input")


def evaluate_output(payload: GuardrailRequest) -> GuardrailResponse:
    return _evaluate(payload, surface="output")


def _evaluate(payload: GuardrailRequest, surface: str) -> GuardrailResponse:
    text = payload.text
    platform_categories = _platform_categories(text)
    redaction = redact(text)
    redaction_categories = _redaction_categories(redaction.counts)

    if platform_categories:
        return _block_response(platform_categories)

    tenant_categories = _tenant_categories(text, payload)
    if tenant_categories:
        return _block_response(tenant_categories, platform_blocked=False, tenant_policy_applied=True)

    if redaction.total:
        return GuardrailResponse(
            allowed=True,
            action="redact",
            decision="allow",
            reason_code=_SAFE_REDACT_REASON,
            message="Content allowed after redaction.",
            refusal=None,
            triggered_rules=redaction_categories,
            categories=redaction_categories,
            redacted_text=redaction.text,
            redaction_summary=RedactionSummary(total=redaction.total, counts=redaction.counts),
            platform_blocked=False,
            tenant_policy_applied=False,
            reason=_SAFE_REDACT_REASON,
        )

    return GuardrailResponse(
        allowed=True,
        action="allow",
        decision="allow",
        reason_code=_SAFE_ALLOW_REASON,
        message=f"{surface} content allowed.",
        refusal=None,
        triggered_rules=[],
        categories=[],
        redacted_text=None,
        redaction_summary=None,
        platform_blocked=False,
        tenant_policy_applied=False,
        reason=_SAFE_ALLOW_REASON,
    )


def _platform_categories(text: str) -> list[str]:
    categories: list[str] = []
    for rule in _PLATFORM_BLOCK_RULES:
        if rule.pattern.search(text):
            categories.append(rule.category)
    return _dedupe(categories)


def _tenant_categories(text: str, payload: GuardrailRequest) -> list[str]:
    rails = payload.context.tenant_rails if payload.context and payload.context.tenant_rails else None
    if rails is None:
        return []
    lowered = text.lower()
    categories: list[str] = []
    for topic in rails.blocked_topics:
        topic = topic.strip().lower()
        if topic and topic in lowered:
            categories.append("tenant_blocked_topic")
    if rails.allowed_topics:
        allowed = [topic.strip().lower() for topic in rails.allowed_topics if topic.strip()]
        if allowed and not any(topic in lowered for topic in allowed):
            categories.append("tenant_allowed_topics")
    return _dedupe(categories)


def _redaction_categories(counts: dict[str, int]) -> list[str]:
    categories: list[str] = []
    for kind in counts:
        if kind in {"email", "phone"}:
            categories.append("pii")
        elif kind == "credit_card":
            categories.append("credit_card")
        elif kind in {"api_key", "bearer_token", "jwt_like", "secret_assignment", "token_like"}:
            categories.append("secret")
        else:
            categories.append(kind)
    return _dedupe(categories)


def _block_response(
    categories: list[str],
    *,
    platform_blocked: bool = True,
    tenant_policy_applied: bool = False,
) -> GuardrailResponse:
    safe_categories = _dedupe(categories)
    return GuardrailResponse(
        allowed=False,
        action="block",
        decision="deny",
        reason_code=safe_categories[0] if safe_categories else _SAFE_BLOCK_REASON,
        message="Content blocked by guardrails.",
        refusal="I can't help with that request.",
        triggered_rules=safe_categories,
        categories=safe_categories,
        redacted_text=None,
        redaction_summary=None,
        platform_blocked=platform_blocked,
        tenant_policy_applied=tenant_policy_applied,
        reason=_SAFE_BLOCK_REASON,
    )


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
