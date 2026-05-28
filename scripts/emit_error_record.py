"""Backstop for CI gate jobs: if the gate runner crashes before writing a
result, this step writes a minimal `status=error` record to the gate's jsonl
so the summary job shows "<gate>: error" instead of the whole pipeline
silently reporting "_no gate artifacts collected_".

Idempotent: if the runner already wrote a record for this gate (success or
failure), we leave it alone — the runner's output is more informative than
ours.

Usage:
    python scripts/emit_error_record.py <gate-name> <jsonl-path>
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: emit_error_record.py <gate> <jsonl-path>", file=sys.stderr)
        return 2

    gate, jsonl_path = argv[1], Path(argv[2])

    if jsonl_path.exists():
        for line in jsonl_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("gate") == gate:
                print(f"backstop: {gate} already has a record; nothing to do")
                return 0

    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "gate": gate,
        "status": "error",
        "observed": None,
        "threshold": None,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "detail": "runner crashed before writing a result; see job log",
    }
    with jsonl_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    print(f"backstop: wrote error record for {gate} to {jsonl_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
