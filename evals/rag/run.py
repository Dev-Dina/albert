"""RAG gate (T082, FR-025).

PLACEHOLDER: each fixture row carries a `retrieved_ids` list (top-k from a
deterministic stub retrieval) so the gate is reproducible in CI without
standing up Postgres + pgvector. Owner B's real RAG harness will replace
the stubbed `retrieved_ids` with a live retrieval call.

Reads BOTH thresholds — `rag.hit_at_5_min` AND `rag.mrr_min`. Both must
pass; reports the more-violated one in OBSERVED on failure.

Run:
    python -m evals.rag.run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from evals.common.gate_report import emit_result
from evals.common.thresholds import get

_GATE = "rag"
_FIXTURE = Path(__file__).parent / "fixtures" / "queries.jsonl"


def _hit_at_k(retrieved: list[str], ground_truth: list[str], k: int = 5) -> float:
    top_k = set(retrieved[:k])
    return 1.0 if any(g in top_k for g in ground_truth) else 0.0


def _rr(retrieved: list[str], ground_truth: list[str]) -> float:
    truth = set(ground_truth)
    for rank, rid in enumerate(retrieved, start=1):
        if rid in truth:
            return 1.0 / rank
    return 0.0


def main() -> int:
    try:
        hit_threshold = float(get("rag", "hit_at_5_min"))
        mrr_threshold = float(get("rag", "mrr_min"))
    except Exception as exc:
        print(f"ERROR loading thresholds: {exc}", file=sys.stderr)
        return emit_result(_GATE, "error", None, None)

    if not _FIXTURE.exists():
        return emit_result(_GATE, "error", None, hit_threshold)

    rows = [json.loads(line) for line in _FIXTURE.read_text().splitlines() if line.strip()]
    if not rows:
        return emit_result(_GATE, "error", None, hit_threshold)

    hits = [_hit_at_k(r["retrieved_ids"], r["ground_truth_chunk_ids"]) for r in rows]
    rrs = [_rr(r["retrieved_ids"], r["ground_truth_chunk_ids"]) for r in rows]
    hit_at_5 = sum(hits) / len(hits)
    mrr = sum(rrs) / len(rrs)

    print(f"hit@5={hit_at_5:.4f} (>= {hit_threshold})  mrr={mrr:.4f} (>= {mrr_threshold})")

    fails: list[str] = []
    if hit_at_5 < hit_threshold:
        fails.append(f"hit_at_5={hit_at_5:.4f} < {hit_threshold}")
    if mrr < mrr_threshold:
        fails.append(f"mrr={mrr:.4f} < {mrr_threshold}")

    if fails:
        # Surface the more-violated metric in OBSERVED for the contract line.
        worst_obs, worst_thr = (
            (hit_at_5, hit_threshold)
            if (hit_threshold - hit_at_5) >= (mrr_threshold - mrr)
            else (mrr, mrr_threshold)
        )
        return emit_result(_GATE, "fail", round(worst_obs, 4), worst_thr)

    return emit_result(_GATE, "pass", round(min(hit_at_5, mrr), 4), min(hit_threshold, mrr_threshold))


if __name__ == "__main__":
    raise SystemExit(main())
