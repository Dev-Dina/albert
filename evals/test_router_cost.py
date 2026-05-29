"""Test the routing cost report (Phase 6.3, brief test #8)."""

from __future__ import annotations

from pathlib import Path

from evals.router_cost import _handler_for_label, run

_GOLDEN = Path(__file__).resolve().parent / "routing_golden.jsonl"


def test_handler_mapping_matches_backend():
    assert _handler_for_label("spam") == "drop"
    assert _handler_for_label("faq_rag") == "rag"
    assert _handler_for_label("lead_capture") == "lead"
    assert _handler_for_label("human_escalate") == "escalate"
    assert _handler_for_label("other_agent") == "agent"
    assert _handler_for_label("unknown") == "agent"


def test_report_prints_routed_off_agent_pct(capsys) -> None:
    rc = run(_GOLDEN)
    out = capsys.readouterr().out
    assert rc == 0
    assert "routed off-agent" in out
    assert "agent-handled" in out
    assert "estimated cost saved" in out
    assert "ESTIMATE" in out  # cost saving is clearly labeled an estimate
    # The committed golden set is majority off-agent.
    import re

    pct = float(re.search(r"routed off-agent: \d+/\d+ = ([\d.]+)%", out).group(1))
    assert pct >= 50.0
