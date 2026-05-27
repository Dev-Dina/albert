"""Tool-selection eval harness.

Usage:
    python -m evals.tool_selection_eval --golden evals/tool_selection.jsonl

Exits non-zero if accuracy < eval_thresholds.yaml[tool_selection_accuracy].
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Keyword-based tool selector (deterministic, no LLM needed for offline eval)
# ---------------------------------------------------------------------------

_RAG_KEYWORDS = {"hours", "opening", "returns", "shipping", "price", "cost", "contact", "support", "policy", "how"}
_CAPTURE_KEYWORDS = {"email", "contact me", "follow up", "get in touch", "sales rep", "reach out"}
_ESCALATE_KEYWORDS = {"manager", "unacceptable", "furious", "angry", "urgent", "emergency", "waiting weeks", "nobody"}


def _predict_tool(message: str) -> str | None:
    """Simple keyword heuristic that mirrors the agent's tool-selection logic."""
    lower = message.lower()

    # Escalate signals — check first (higher priority)
    if any(kw in lower for kw in _ESCALATE_KEYWORDS):
        return "escalate"

    # Lead capture signals
    if any(kw in lower for kw in _CAPTURE_KEYWORDS):
        return "capture_lead"

    # RAG search signals
    if any(kw in lower for kw in _RAG_KEYWORDS):
        return "rag_search"

    return None  # direct answer, no tool


# ---------------------------------------------------------------------------
# Eval runner
# ---------------------------------------------------------------------------

def run_eval(golden_path: Path, thresholds_path: Path) -> int:
    examples = [json.loads(line) for line in golden_path.read_text().splitlines() if line.strip()]

    thresholds = yaml.safe_load(thresholds_path.read_text())
    threshold = float(thresholds.get("tool_selection_accuracy", 0.8))

    correct = 0
    total = len(examples)

    print(f"\nTool-selection eval — {total} examples\n{'=' * 50}")
    for i, ex in enumerate(examples, 1):
        msg = ex["message"]
        expected = ex.get("expected_tool")
        predicted = _predict_tool(msg)
        passed = predicted == expected
        if passed:
            correct += 1
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] #{i:02d}  expected={expected!r:15}  predicted={predicted!r:15}  msg={msg[:50]!r}")

    accuracy = correct / total if total else 0.0
    print(f"\n{'=' * 50}")
    print(f"Accuracy: {correct}/{total} = {accuracy:.2%}  (threshold: {threshold:.0%})")

    if accuracy < threshold:
        print(f"FAIL — accuracy {accuracy:.2%} is below threshold {threshold:.0%}")
        return 1

    print("PASS")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Tool-selection eval harness")
    parser.add_argument("--golden", default="evals/tool_selection.jsonl", help="Path to golden JSONL")
    parser.add_argument(
        "--thresholds", default="evals/eval_thresholds.yaml", help="Path to thresholds YAML"
    )
    args = parser.parse_args()

    golden_path = Path(args.golden)
    thresholds_path = Path(args.thresholds)

    if not golden_path.exists():
        print(f"ERROR: golden file not found: {golden_path}", file=sys.stderr)
        sys.exit(1)

    if not thresholds_path.exists():
        print(f"ERROR: thresholds file not found: {thresholds_path}", file=sys.stderr)
        sys.exit(1)

    sys.exit(run_eval(golden_path, thresholds_path))


if __name__ == "__main__":
    main()
