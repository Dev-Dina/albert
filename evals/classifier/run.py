"""Classifier eval gate (T080, FR-023).

PLACEHOLDER: scores a small fixture set by reading pre-computed `label` and
`predicted` columns. Owner C drops in the real classifier + dataset; the
threshold key (`classifier.macro_f1_min`) and gate name stay the same.

Run:
    python -m evals.classifier.run
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from evals.common.gate_report import emit_result
from evals.common.thresholds import get

_GATE = "classifier"
_FIXTURE = Path(__file__).parent / "fixtures" / "labels.jsonl"


def _macro_f1(rows: list[dict]) -> float:
    per_label_tp: dict[str, int] = defaultdict(int)
    per_label_fp: dict[str, int] = defaultdict(int)
    per_label_fn: dict[str, int] = defaultdict(int)
    labels: set[str] = set()
    for row in rows:
        truth = row["label"]
        pred = row["predicted"]
        labels.add(truth)
        labels.add(pred)
        if truth == pred:
            per_label_tp[truth] += 1
        else:
            per_label_fp[pred] += 1
            per_label_fn[truth] += 1

    f1_scores: list[float] = []
    for label in labels:
        tp = per_label_tp[label]
        fp = per_label_fp[label]
        fn = per_label_fn[label]
        if tp == 0 and fp == 0 and fn == 0:
            continue
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        denom = precision + recall
        f1 = (2 * precision * recall / denom) if denom else 0.0
        f1_scores.append(f1)
    return sum(f1_scores) / len(f1_scores) if f1_scores else 0.0


def main() -> int:
    try:
        threshold = float(get("classifier", "macro_f1_min"))
    except Exception as exc:
        print(f"ERROR loading threshold: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, None)

    if not _FIXTURE.exists():
        print(f"ERROR: fixture missing at {_FIXTURE}", file=sys.stderr)
        return emit_result(_GATE, "error", None, threshold)

    rows = [json.loads(line) for line in _FIXTURE.read_text().splitlines() if line.strip()]
    if not rows:
        return emit_result(_GATE, "error", None, threshold)

    observed = _macro_f1(rows)
    status = "pass" if observed >= threshold else "fail"
    return emit_result(_GATE, status, round(observed, 4), threshold)


if __name__ == "__main__":
    raise SystemExit(main())
