"""Redaction gate (T084, FR-027).

PLACEHOLDER: a tiny regex-based redactor stand-in scrubs each planted secret
from the response surface; the gate asserts the secret does not survive in
the "captured response", a sample "log line", or a sample "stored trace"
(all three are constructed in-process here — Owner C's real redaction layer
+ harness drops in, gate name and threshold key stay the same).

MUST achieve 1.00 to pass (FR-027).

Run:
    python -m evals.redaction.run
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from evals.common.gate_report import emit_result
from evals.common.thresholds import get

_GATE = "redaction"
_FIXTURE = Path(__file__).parent / "fixtures" / "planted_secrets.jsonl"

_REDACTION_PATTERNS = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),                          # SSN
    re.compile(r"\b(?:\d[ -]?){13,19}\b"),                         # CC (loose, greedy)
    re.compile(r"\bsk-[A-Za-z0-9\-]{8,}\b"),                       # fake API key
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),                   # email
    re.compile(r"\+?\d[\d\s\-().]{7,}\d"),                         # phone
]


def _redact(text: str) -> str:
    out = text
    for pat in _REDACTION_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def _surfaces(raw: str) -> dict[str, str]:
    """Three places a leak might surface: response body, log line, stored trace."""
    redacted = _redact(raw)
    return {
        "response_body": redacted,
        "log_line": f"event=chat_reply payload={redacted}",
        "stored_trace": json.dumps({"text": redacted}),
    }


def main() -> int:
    try:
        threshold = float(get("redaction", "required_pass_rate"))
    except Exception as exc:
        print(f"ERROR loading threshold: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, None)

    if threshold != 1.0:
        print(
            f"ERROR: redaction.required_pass_rate must be exactly 1.0, got {threshold}",
            file=sys.stderr,
        )
        return emit_result(_GATE, "error", threshold, 1.0)

    if not _FIXTURE.exists():
        return emit_result(_GATE, "error", None, threshold)

    cases = [json.loads(line) for line in _FIXTURE.read_text().splitlines() if line.strip()]
    if not cases:
        return emit_result(_GATE, "error", None, threshold)

    leaks: list[tuple[str, str, str]] = []
    passed = 0
    for case in cases:
        surfaces = _surfaces(case["raw"])
        leaked_in_this_case = False
        for surface_name, surface_text in surfaces.items():
            for needle in case["must_not_appear"]:
                if needle in surface_text:
                    leaks.append((case["id"], surface_name, needle))
                    leaked_in_this_case = True
        if not leaked_in_this_case:
            passed += 1

    observed = passed / len(cases)
    for case_id, surface, needle in leaks:
        print(f"  LEAK case={case_id} surface={surface} needle={needle!r}")

    status = "pass" if observed >= threshold else "fail"
    return emit_result(_GATE, status, round(observed, 4), threshold)


if __name__ == "__main__":
    raise SystemExit(main())
