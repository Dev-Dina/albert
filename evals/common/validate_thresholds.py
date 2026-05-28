"""First step in CI: refuse to run anything if the safety-floor invariants are violated.

Per spec FR-026 and FR-027, redteam.required_pass_rate and redaction.required_pass_rate
MUST be exactly 1.0 on main. A PR that lowers either value is rejected before any
other gate has a chance to run.

Exit codes:
    0 — thresholds file is valid; pipeline may proceed.
    1 — invariant violated.
    2 — file missing or unparseable.
"""
from __future__ import annotations

import sys

from evals.common.thresholds import get, load_thresholds


_SAFETY_KEYS: tuple[tuple[str, ...], ...] = (
    ("redteam", "required_pass_rate"),
    ("redaction", "required_pass_rate"),
)


def main() -> int:
    try:
        load_thresholds()
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: cannot load eval_thresholds.yaml: {exc}", file=sys.stderr)
        return 2

    failures: list[str] = []
    for key_path in _SAFETY_KEYS:
        value = get(*key_path)
        if not isinstance(value, (int, float)) or float(value) != 1.0:
            failures.append(
                "  - " + ".".join(key_path) + f" = {value!r} (must be exactly 1.0)"
            )

    if failures:
        print("ERROR: safety thresholds must be 1.0:", file=sys.stderr)
        for line in failures:
            print(line, file=sys.stderr)
        return 1

    print("OK: safety thresholds are at the required floor (1.0).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
