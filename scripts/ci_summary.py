"""CI summary step (T087, FR-029).

Reads every `ci-gate-results.jsonl` produced by the per-gate jobs (downloaded
by the workflow into `collected-artifacts/<artifact-name>/`), renders a
markdown table to `$GITHUB_STEP_SUMMARY`, and exits non-zero if any gate
failed so the workflow goes red.

Also surfaces total wall-clock vs `ci.total_budget_seconds` from
`eval_thresholds.yaml` (SC-006). For v1 this is a soft signal — the row is
rendered but the script does NOT fail the build on overage. Flip the
`_HARD_TIME_GATE` flag here after a few weeks of measured run-times to
promote it to a hard gate.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import yaml

_HARD_TIME_GATE = False  # flip to True once we have stable run-time data.

# Every gate the pipeline is contractually required to report on
# (contracts/ci-gate.contract.md). If any of these is missing from the
# collected artifacts — usually because the gate job was skipped after smoke
# failed — the summary synthesises an `error` row so the failure names the
# specific gate(s) instead of going blank.
_EXPECTED_GATES: tuple[str, ...] = (
    "classifier",
    "agent_tool_selection",
    "rag",
    "redteam_cross_tenant",
    "redaction",
)


def _load_records(root: Path) -> list[dict]:
    records: list[dict] = []
    if not root.exists():
        return records
    for jsonl in root.rglob("ci-gate-results.jsonl"):
        for line in jsonl.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"WARN: bad jsonl line in {jsonl}: {exc}", file=sys.stderr)
    # De-dupe in case the same artifact got attached twice.
    seen: set[str] = set()
    unique: list[dict] = []
    for r in records:
        key = f"{r.get('gate')}::{r.get('status')}::{r.get('observed')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def _fmt(value: object) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _budget_row() -> tuple[str, bool] | None:
    """Return (markdown_row, fail) for the wall-clock soft signal, or None."""
    start_iso = os.environ.get("GATE_RUN_START")
    if not start_iso:
        return None
    try:
        budget = float(
            yaml.safe_load(Path("eval_thresholds.yaml").read_text())["ci"][
                "total_budget_seconds"
            ]
        )
    except Exception:
        return None
    try:
        # GitHub gives an ISO-8601 timestamp; parse with strptime.
        start_epoch = time.mktime(time.strptime(start_iso, "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return None
    observed = max(0.0, time.time() - start_epoch)
    status = "pass" if observed <= budget else "fail"
    row = f"| ci_total_wallclock_seconds (soft) | {status} | {observed:.1f} | {budget:.0f} |"
    return row, (status == "fail" and _HARD_TIME_GATE)


def main() -> int:
    root = Path("collected-artifacts")
    records = _load_records(root)

    lines = [
        "## CI gate summary",
        "",
        "| gate | status | observed | threshold |",
        "|---|---|---|---|",
    ]

    failed: list[str] = []

    # Synthesise an error row for any contract-required gate that produced
    # no artifact (typically because the job was skipped after smoke failed,
    # so the per-job `if: failure()` backstop never ran). Without this the
    # whole table reads as one ambiguous "no gate artifacts collected" row.
    seen_gates = {r["gate"] for r in records}
    for gate in _EXPECTED_GATES:
        if gate not in seen_gates:
            records.append(
                {
                    "gate": gate,
                    "status": "error",
                    "observed": None,
                    "threshold": None,
                    "detail": "no artifact uploaded (job skipped or crashed before backstop)",
                }
            )

    # Stable order: contract gates first, then anything else alphabetical.
    order = list(_EXPECTED_GATES)
    records.sort(key=lambda r: (
        order.index(r["gate"]) if r["gate"] in order else len(order),
        r["gate"],
    ))
    for r in records:
        lines.append(
            f"| {r['gate']} | {r['status']} | {_fmt(r.get('observed'))} | {_fmt(r.get('threshold'))} |"
        )
        if r["status"] != "pass":
            failed.append(r["gate"])

    budget = _budget_row()
    if budget is not None:
        lines.append(budget[0])
        if budget[1]:
            failed.append("ci_total_wallclock_seconds")

    summary_md = "\n".join(lines) + "\n"
    print(summary_md)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).parent.mkdir(parents=True, exist_ok=True)
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(summary_md)

    if failed:
        first = failed[0]
        # Find the matching record to enrich the message with observed/threshold.
        for r in records:
            if r["gate"] == first:
                print(
                    f"::error title=CI / {first} failed::"
                    f"{first} observed={_fmt(r.get('observed'))} "
                    f"threshold={_fmt(r.get('threshold'))}"
                )
                break
        else:
            print(f"::error title=CI / {first} failed::see job logs")
        return 1

    print("::notice title=CI summary::all gates passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
