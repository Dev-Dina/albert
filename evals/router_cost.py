"""Routing cost report (Phase 6.3): share of turns handled off the agent.

Deterministic report over the committed routing golden set
(``evals/routing_golden.jsonl``). Each expected classifier label maps to its
cheap-path handler (mirrors
``backend/app/services/router.py::handler_for_label``); turns NOT routed to the
bounded LLM agent are "off-agent". Reports off-agent vs agent share plus an
ESTIMATED cost saved.

This is a reporting tool, not a CI gate — it has no threshold. The mapping is
inlined (not imported from the backend) so the report runs standalone like the
other evals, without the backend package on the path.

Usage:
    python -m evals.router_cost --golden evals/routing_golden.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Mirror of backend router handler_for_label. Keep in sync with
# backend/app/services/router.py::_LABEL_HANDLER.
_LABEL_HANDLER = {
    "spam": "drop",
    "faq_rag": "rag",
    "lead_capture": "lead",
    "human_escalate": "escalate",
    "other_agent": "agent",
}
_OFF_AGENT_HANDLERS = {"drop", "rag", "lead", "escalate"}

# ESTIMATE ONLY — assumed marginal cost of one bounded agent turn (several LLM
# calls) that a cheap path avoids. A documented assumption, NOT a measured bill;
# replace with real telemetry when available.
_EST_AGENT_USD_PER_TURN = 0.002


def _handler_for_label(label: str) -> str:
    return _LABEL_HANDLER.get(label, "agent")


def run(golden_path: Path) -> int:
    rows = [json.loads(line) for line in golden_path.read_text().splitlines() if line.strip()]
    total = len(rows)
    if total == 0:
        print("ERROR: routing golden set is empty", file=sys.stderr)
        return 2

    per_handler: dict[str, int] = {}
    off_agent = 0
    for row in rows:
        handler = _handler_for_label(row["label"])
        per_handler[handler] = per_handler.get(handler, 0) + 1
        if handler in _OFF_AGENT_HANDLERS:
            off_agent += 1

    agent = total - off_agent
    off_pct = off_agent / total * 100
    agent_pct = agent / total * 100
    est_saved = off_agent * _EST_AGENT_USD_PER_TURN

    print(f"Routing cost report — {total} golden turns")
    print("-" * 48)
    for handler in ("drop", "rag", "lead", "escalate", "agent"):
        count = per_handler.get(handler, 0)
        print(f"  {handler:9} {count:3d}  ({count / total * 100:5.1f}%)")
    print("-" * 48)
    print(f"routed off-agent: {off_agent}/{total} = {off_pct:.1f}%")
    print(f"agent-handled:    {agent}/{total} = {agent_pct:.1f}%")
    print(
        f"estimated cost saved: ${est_saved:.4f}  "
        f"[ESTIMATE — assumes ${_EST_AGENT_USD_PER_TURN:.4f}/agent turn avoided]"
    )
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Routing cost report")
    parser.add_argument("--golden", default="evals/routing_golden.jsonl", help="Path to routing golden JSONL")
    args = parser.parse_args()
    golden_path = Path(args.golden)
    if not golden_path.exists():
        print(f"ERROR: golden file not found: {golden_path}", file=sys.stderr)
        sys.exit(1)
    sys.exit(run(golden_path))


if __name__ == "__main__":
    main()
