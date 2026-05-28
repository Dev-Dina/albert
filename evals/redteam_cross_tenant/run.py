"""Cross-tenant red-team gate (T083, FR-026).

Delegates to `backend/tests/redteam/cross_tenant_demo.py::run_all()` — the
single source of truth for the attack inventory (also used by the quickstart).
This gate enforces the inventory matches `expected_failures.json` and that
every attack was rejected (1.00 pass rate, no exceptions).

Run from repo root:
    python -m evals.redteam_cross_tenant.run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Make `app.*` and `tests.*` importable when run from repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from evals.common.gate_report import emit_result  # noqa: E402
from evals.common.thresholds import get  # noqa: E402

_GATE = "redteam_cross_tenant"
_INVENTORY = Path(__file__).parent / "fixtures" / "expected_failures.json"


def main() -> int:
    try:
        threshold = float(get("redteam", "required_pass_rate"))
    except Exception as exc:
        print(f"ERROR loading threshold: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, None)

    if threshold != 1.0:
        print(
            f"ERROR: redteam.required_pass_rate must be exactly 1.0, got {threshold}",
            file=sys.stderr,
        )
        return emit_result(_GATE, "error", threshold, 1.0)

    if not _INVENTORY.exists():
        return emit_result(_GATE, "error", None, threshold)

    inventory = json.loads(_INVENTORY.read_text())
    expected_names = {a["name"] for a in inventory["attempts"]}

    try:
        from tests.redteam.cross_tenant_demo import run_all
    except Exception as exc:  # pragma: no cover — import failure is a hard error
        print(f"ERROR importing red-team harness: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, threshold)

    try:
        results = run_all()
    except Exception as exc:  # pragma: no cover
        print(f"ERROR running red-team attacks: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, threshold)

    actual_names = {r.name for r in results}
    missing = expected_names - actual_names
    if missing:
        print(
            "ERROR: harness missing expected attack(s): " + ", ".join(sorted(missing)),
            file=sys.stderr,
        )
        return emit_result(_GATE, "error", None, threshold)

    rejected = sum(1 for r in results if r.rejected)
    observed = rejected / len(results)
    for r in results:
        verdict = "REJECT" if r.rejected else "BREACH"
        print(f"  [{verdict}] {r.name}: {r.detail}")

    status = "pass" if observed >= threshold else "fail"
    return emit_result(_GATE, status, round(observed, 4), threshold)


if __name__ == "__main__":
    raise SystemExit(main())
