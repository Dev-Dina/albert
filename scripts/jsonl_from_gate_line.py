"""Extract the `GATE=… STATUS=… OBSERVED=… THRESHOLD=…` contract line from a
gate runner's captured stdout and append it as a jsonl record at the path the
summary job collects (`artifacts/ci-gate-results.jsonl`).

Used for runners that don't write the artifact themselves (currently Owner C's
classifier gate, which only prints to stdout per docs/OWNER_C_CI_HANDOFF.md).

Usage:
    python scripts/jsonl_from_gate_line.py <gate-name> <stdout-file> <jsonl-out>
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

_LINE_RE = re.compile(
    r"^GATE=(?P<gate>\S+)\s+STATUS=(?P<status>\S+)\s+OBSERVED=(?P<observed>\S+)\s+THRESHOLD=(?P<threshold>\S+)"
)


def _coerce(value: str) -> float | str:
    if value == "NA":
        return "NA"
    try:
        return float(value)
    except ValueError:
        return value


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        print("usage: jsonl_from_gate_line.py <gate> <stdout-file> <jsonl-out>", file=sys.stderr)
        return 2

    expected_gate, stdout_path, out_path = argv[1], Path(argv[2]), Path(argv[3])
    if not stdout_path.exists():
        print(f"ERROR: stdout file missing: {stdout_path}", file=sys.stderr)
        return 2

    match = None
    for line in stdout_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LINE_RE.match(line.strip())
        if m:
            match = m  # keep the last match — gate may print intermediate lines

    if match is None:
        print(
            f"ERROR: no GATE=... line found in {stdout_path}; emitting error record",
            file=sys.stderr,
        )
        record = {
            "gate": expected_gate,
            "status": "error",
            "observed": None,
            "threshold": None,
            "run_id": os.environ.get("GITHUB_RUN_ID"),
        }
    else:
        record = {
            "gate": match.group("gate"),
            "status": match.group("status"),
            "observed": _coerce(match.group("observed")),
            "threshold": _coerce(match.group("threshold")),
            "run_id": os.environ.get("GITHUB_RUN_ID"),
        }
        if record["gate"] != expected_gate:
            print(
                f"WARN: gate name mismatch — line said {record['gate']!r}, "
                f"job expected {expected_gate!r}; using line value",
                file=sys.stderr,
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return 0 if match is not None and record["status"] == "pass" else (
        1 if match is not None else 2
    )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
