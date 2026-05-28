"""Tool-selection eval gate (T081, FR-024).

PLACEHOLDER: uses a tiny keyword heuristic to "predict" the tool for each
fixture message; Owner B's agent + golden set drops in over this file.
Threshold key (`agent_tool_selection.accuracy_min`) and gate name are stable.

Run:
    python -m evals.tool_selection.run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.common.gate_report import emit_result
from evals.common.thresholds import get

_GATE = "agent_tool_selection"
_FIXTURE = Path(__file__).parent / "fixtures" / "cases.jsonl"

_RAG = {"hours", "ship", "shipping", "returns", "return", "policy", "price", "cost"}
_CAPTURE = {"email", "follow up", "contact me", "reach out"}
_ESCALATE = {"manager", "human", "escalate", "speak to a person"}


def _predict(message: str) -> str | None:
    lower = message.lower()
    if any(kw in lower for kw in _ESCALATE):
        return "escalate"
    if any(kw in lower for kw in _CAPTURE):
        return "capture_lead"
    if any(kw in lower for kw in _RAG):
        return "rag_search"
    return None


def main() -> int:
    try:
        threshold = float(get("agent_tool_selection", "accuracy_min"))
    except Exception as exc:
        print(f"ERROR loading threshold: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, None)

    if not _FIXTURE.exists():
        return emit_result(_GATE, "error", None, threshold)

    cases = [json.loads(line) for line in _FIXTURE.read_text().splitlines() if line.strip()]
    if not cases:
        return emit_result(_GATE, "error", None, threshold)

    correct = sum(1 for c in cases if _predict(c["message"]) == c["expected_tool"])
    observed = correct / len(cases)
    status = "pass" if observed >= threshold else "fail"
    return emit_result(_GATE, status, round(observed, 4), threshold)


if __name__ == "__main__":
    raise SystemExit(main())
