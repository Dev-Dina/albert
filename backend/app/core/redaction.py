"""Deterministic, regex-first redaction (SPEC §7).

Redacts secrets/PII from text before it can reach logs, traces, memory, or error
outputs. Stdlib only. Fails closed: if redaction errors internally, a fully
redacted-safe value is returned — never the raw text. Callers/logs may surface
redaction *types and counts*, never raw values.
"""

import logging
import re
from dataclasses import dataclass, field

_PLACEHOLDERS: dict[str, str] = {
    "api_key": "[REDACTED_API_KEY]",
    "bearer_token": "[REDACTED_TOKEN]",
    "credit_card": "[REDACTED_CREDIT_CARD]",
    "email": "[REDACTED_EMAIL]",
    "jwt_like": "[REDACTED_TOKEN]",
    "phone": "[REDACTED_PHONE]",
    "secret_assignment": "[REDACTED_TOKEN]",
    "token_like": "[REDACTED_TOKEN]",
}

# Ordered most-specific → least-specific. Earlier matches consume the text so a
# later, broader pattern cannot re-match (and cannot double-count) the same span.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # key=value / key: value secret assignments (case-insensitive key).
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|service[_-]?auth[_-]?token|token|password|passwd|pwd|secret"
            r"|client[_-]?secret)\b\s*[:=]\s*['\"]?[^\s'\"]+['\"]?"
        ),
    ),
    # Authorization: Bearer <token>.
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")),
    # Emails.
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # Common prefixed API-key shapes (Gemini, OpenAI, Groq, Stripe, AWS, GitHub, Slack).
    (
        "api_key",
        re.compile(
            r"\bAIza[0-9A-Za-z_\-]{20,}\b"
            r"|\b(?:sk|pk|rk|gsk)_[A-Za-z0-9_\-]{8,}\b"
            r"|\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b"
            r"|\bAKIA[0-9A-Z]{16}\b"
            r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
            r"|\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"
        ),
    ),
    # JWT-like tokens: header.payload.signature.
    (
        "jwt_like",
        re.compile(
            r"\b[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"
        ),
    ),
    # Credit-card-like digit groups.
    ("credit_card", re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)")),
    # Generic long token-like strings (hex / base64-ish).
    ("token_like", re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")),
    # Phone numbers (conservative).
    ("phone", re.compile(r"(?<!\w)\+?\d[\d().\-\s]{7,}\d(?!\w)")),
)


@dataclass
class RedactionResult:
    """Outcome of a redaction pass: safe text + per-type counts (no raw values)."""

    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str) -> RedactionResult:
    """Redact secrets/PII deterministically. Fails closed on internal error."""
    try:
        if not isinstance(text, str):
            text = str(text)
        counts: dict[str, int] = {}
        redacted = text
        for kind, pattern in _PATTERNS:
            redacted, n = pattern.subn(_PLACEHOLDERS[kind], redacted)
            if n:
                counts[kind] = n
        return RedactionResult(text=redacted, counts=counts)
    except Exception:
        # Fail closed: never return raw text if detection errors.
        return RedactionResult(text="[REDACTED]", counts={"error": 1})


class RedactionFilter(logging.Filter):
    """Logging filter that redacts a record's fully-rendered message.

    Redacts ``record.getMessage()`` and clears ``record.args`` so the formatter
    cannot re-insert raw secrets via ``%`` substitution.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            # If rendering the message fails, fail closed rather than risk a leak.
            record.msg = "[REDACTED]"
            record.args = ()
            return True
        record.msg = redact(message).text
        record.args = ()
        return True


_FILTER_INSTALLED_ATTR = "_albert_redaction_filter_installed"


def install_redaction_filter() -> None:
    """Install :class:`RedactionFilter` on the root logger's handlers.

    Idempotent (handlers are marked once). Does not modify ``core/logging.py`` —
    it attaches to whatever handlers root logging setup has already created.
    """
    root = logging.getLogger()
    for handler in root.handlers:
        if getattr(handler, _FILTER_INSTALLED_ATTR, False):
            continue
        handler.addFilter(RedactionFilter())
        setattr(handler, _FILTER_INSTALLED_ATTR, True)
