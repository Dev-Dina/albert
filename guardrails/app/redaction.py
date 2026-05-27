from __future__ import annotations

import re
from dataclasses import dataclass, field

_PLACEHOLDER = "[REDACTED:{kind}]"

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "secret_assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|apikey|token|password|passwd|pwd|secret"
            r"|client[_-]?secret)\b\s*[:=]\s*['\"]?[^\s'\"]+['\"]?"
        ),
    ),
    ("bearer_token", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]+")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    (
        "api_key",
        re.compile(
            r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b"
            r"|\bAKIA[0-9A-Z]{16}\b"
            r"|\bgh[pousr]_[A-Za-z0-9]{20,}\b"
            r"|\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"
        ),
    ),
    (
        "credit_card",
        re.compile(r"(?<!\d)(?:\d[ -]*?){13,19}(?!\d)"),
    ),
    ("token_like", re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")),
    ("phone", re.compile(r"(?<!\w)\+?\d[\d().\-\s]{7,}\d(?!\w)")),
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str) -> RedactionResult:
    try:
        redacted = str(text)
        counts: dict[str, int] = {}
        for kind, pattern in _PATTERNS:
            redacted, count = pattern.subn(_PLACEHOLDER.format(kind=kind), redacted)
            if count:
                counts[kind] = count
        return RedactionResult(text=redacted, counts=counts)
    except Exception:
        return RedactionResult(text="[REDACTED]", counts={"error": 1})
