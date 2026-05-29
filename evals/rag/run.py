"""Artifact-producing wrapper for the 15-case offline RAG eval.

The substantive metrics live in `evals.rag_eval`: hit@5, MRR, faithfulness,
and answer relevancy over the committed golden triples, where faithfulness and
answer relevancy are scored by a frozen offline judge rubric (not RAGAS, not an
LLM judge). When the hand-labeled subset `evals/rag_judge_labels.jsonl` is
present, this wrapper also reports judge↔human agreement.

This wrapper keeps the CI gate-report contract used by the summary job, and
additionally records the full metric breakdown (incl. judge_agreement) on the
gate's jsonl record. The summary parser only reads gate/status/observed/
threshold, so the extra keys are additive and safe.

Run:
    python -m evals.rag.run
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from evals.common.gate_report import _ARTIFACT_PATH, _format_value
from evals.rag_eval import (
    compute_agreement,
    evaluate_with_examples,
    failures,
    load_golden,
    load_labels,
    load_thresholds,
    print_report,
)

_GATE = "rag"
_GOLDEN = Path(__file__).resolve().parents[1] / "rag_golden.jsonl"
_LABELS = Path(__file__).resolve().parents[1] / "rag_judge_labels.jsonl"


def _emit(status: str, observed: float | None, threshold: float | None, metrics, agreement) -> int:
    """Print the contract line and append an enriched jsonl record.

    Base fields (gate/status/observed/threshold/run_id) match the shared
    gate contract; the per-metric breakdown is additive.
    """
    print(
        f"GATE={_GATE} STATUS={status} "
        f"OBSERVED={_format_value(observed)} THRESHOLD={_format_value(threshold)}"
    )
    _ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "gate": _GATE,
        "status": status,
        "observed": observed,
        "threshold": threshold,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "hit_at_5": round(metrics.hit_at_5, 4) if metrics else None,
        "mrr": round(metrics.mrr, 4) if metrics else None,
        "faithfulness": round(metrics.faithfulness, 4) if metrics else None,
        "answer_relevancy": round(metrics.answer_relevancy, 4) if metrics else None,
        "judge_agreement": round(agreement.score, 4) if agreement else None,
    }
    with _ARTIFACT_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return {"pass": 0, "fail": 1, "error": 2}[status]


def main() -> int:
    try:
        triples = load_golden(_GOLDEN)
        thresholds = load_thresholds()
        metrics, examples = evaluate_with_examples(triples)
        agreement = None
        if _LABELS.exists():
            agreement = compute_agreement(examples, load_labels(_LABELS), thresholds)
    except Exception as exc:
        print(f"ERROR: RAG gate could not run: {exc}", file=sys.stderr)
        return _emit("error", None, None, None, None)

    print_report(metrics, thresholds, agreement)
    failed = failures(metrics, thresholds, agreement)
    observed = min(metrics.hit_at_5, metrics.mrr, metrics.faithfulness, metrics.answer_relevancy)
    threshold = min(thresholds.values())
    if failed:
        for failure in failed:
            print(f"FAIL: {failure}")
        return _emit("fail", round(observed, 4), threshold, metrics, agreement)
    return _emit("pass", round(observed, 4), threshold, metrics, agreement)


if __name__ == "__main__":
    raise SystemExit(main())
