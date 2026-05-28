"""Shared CI-gate output helpers (contracts/ci-gate.contract.md).

Every `evals/<gate>/run.py` calls `emit_result(...)` to produce both the
single human-readable final line and the jsonl artifact the summary job
collects from `artifacts/ci-gate-results.jsonl`. Centralising the format
keeps every gate identical so the summary step in `.github/workflows/ci.yml`
can parse one schema.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

Status = Literal["pass", "fail", "error"]

_ARTIFACT_PATH = Path("artifacts") / "ci-gate-results.jsonl"


def _format_value(value: float | str | None) -> str:
    if value is None:
        return "NA"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def emit_result(
    gate: str,
    status: Status,
    observed: float | str | None,
    threshold: float | str | None,
    artifact_path: Path | None = None,
) -> int:
    """Print the contract's final line and append a jsonl record.

    Returns the exit code per the gate contract: 0 (pass), 1 (fail), 2 (error).
    """
    obs = _format_value(observed)
    thr = _format_value(threshold)
    print(f"GATE={gate} STATUS={status} OBSERVED={obs} THRESHOLD={thr}")

    target = artifact_path or _ARTIFACT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "gate": gate,
        "status": status,
        "observed": observed,
        "threshold": threshold,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
    }
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    return {"pass": 0, "fail": 1, "error": 2}[status]
