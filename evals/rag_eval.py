"""Offline deterministic RAG evaluation harness.

Measures retrieval (hit@5, MRR) and generation quality (faithfulness, answer
relevancy) against the committed 15-triple golden set.

Generation quality is scored by a **frozen offline judge rubric** — a
version-controlled, deterministic key-term-coverage rubric. It is deliberately
NOT RAGAS and NOT an LLM-as-judge: the CI gate must run on a fresh clone with
no hosted API keys. The rubric is:

* answer relevancy = ideal-answer key-term coverage in the generated answer
* faithfulness    = generated-answer key-term support in the retrieved context

To keep the frozen judge honest, a small hand-labeled subset
(`evals/rag_judge_labels.jsonl`) records a human pass/fail verdict per example.
When supplied via `--labels`, the harness reports the agreement between the
frozen judge's pass/fail decisions and the human labels. This satisfies the
brief's "frozen judge + report agreement with hand labels" option without any
hosted LLM judge.

Limitation: the frozen judge is lexical, not semantic. It is a CI-safe grading
floor, not a replacement for a semantic LLM judge or RAGAS in deeper offline
reviews.

Usage:
    uv run --project backend python -m evals.rag_eval --golden evals/rag_golden.jsonl
    uv run --project backend python -m evals.rag_eval --golden evals/rag_golden.jsonl \
        --labels evals/rag_judge_labels.jsonl

Exit codes:
    0 - all metrics meet thresholds
    1 - one or more metrics below threshold
    2 - invalid golden set, label set, or threshold configuration
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evals.common.thresholds import get as get_threshold

EXPECTED_TRIPLE_COUNT = 15
TOP_K = 5

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "do",
    "does",
    "for",
    "how",
    "i",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "our",
    "the",
    "there",
    "to",
    "we",
    "what",
    "where",
    "with",
    "you",
    "your",
}


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str


@dataclass(frozen=True)
class RagMetrics:
    hit_at_5: float
    mrr: float
    faithfulness: float
    answer_relevancy: float
    count: int


@dataclass(frozen=True)
class ExampleResult:
    """Per-example frozen-judge scores plus the inputs needed to re-judge a
    calibration override (candidate_answer) against the same question."""

    id: str
    faithfulness: float
    answer_relevancy: float
    ideal_answer: str
    context: str


@dataclass(frozen=True)
class Agreement:
    """Agreement between frozen-judge pass/fail decisions and human labels."""

    score: float
    matches: int
    total: int


def load_golden(path: str | Path) -> list[dict[str, Any]]:
    triples: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line"] = line_number
                triples.append(row)
    _validate_golden(triples)
    return triples


def load_labels(path: str | Path) -> list[dict[str, Any]]:
    """Load the optional hand-labeled subset used for judge-agreement reporting."""
    labels: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if line.strip():
                row = json.loads(line)
                row["_line"] = line_number
                labels.append(row)
    _validate_labels(labels)
    return labels


def load_thresholds() -> dict[str, float]:
    thresholds = {
        "hit_at_5": float(get_threshold("rag", "hit_at_5_min")),
        "mrr": float(get_threshold("rag", "mrr_min")),
        "faithfulness": float(get_threshold("rag", "faithfulness_min")),
        "answer_relevancy": float(get_threshold("rag", "answer_relevancy_min")),
    }
    # Optional: only enforced when a hand-labeled subset is supplied.
    try:
        thresholds["judge_agreement"] = float(get_threshold("rag", "judge_agreement_min"))
    except KeyError:
        pass
    return thresholds


def compute_hit_at_k(retrieved_ids: list[str], ground_truth_ids: list[str], k: int = TOP_K) -> float:
    top_k = set(retrieved_ids[:k])
    return 1.0 if any(g in top_k for g in ground_truth_ids) else 0.0


def compute_rr(retrieved_ids: list[str], ground_truth_ids: list[str]) -> float:
    ground_set = set(ground_truth_ids)
    for rank, chunk_id in enumerate(retrieved_ids, start=1):
        if chunk_id in ground_set:
            return 1.0 / rank
    return 0.0


def frozen_judge_relevancy(ideal_answer: str, generated_answer: str) -> float:
    """Frozen offline judge: does the generated answer cover the reference answer's key terms?

    Deterministic, version-controlled rubric — NOT RAGAS, NOT an LLM judge.
    """
    return _coverage(_key_terms(ideal_answer), generated_answer)


def frozen_judge_faithfulness(generated_answer: str, context: str) -> float:
    """Frozen offline judge: are the generated answer's key terms supported by retrieved context?

    Deterministic, version-controlled rubric — NOT RAGAS, NOT an LLM judge.
    """
    return _coverage(_key_terms(generated_answer), context)


def evaluate(triples: list[dict[str, Any]]) -> RagMetrics:
    metrics, _ = evaluate_with_examples(triples)
    return metrics


def evaluate_with_examples(
    triples: list[dict[str, Any]],
) -> tuple[RagMetrics, list[ExampleResult]]:
    corpus = _build_corpus(triples)
    hit_scores: list[float] = []
    rr_scores: list[float] = []
    faithfulness_scores: list[float] = []
    relevancy_scores: list[float] = []
    examples: list[ExampleResult] = []

    for triple in triples:
        retrieved_chunks = retrieve_offline(triple["question"], corpus, top_k=TOP_K)
        retrieved_ids = [chunk.id for chunk in retrieved_chunks]
        context = " ".join(chunk.text for chunk in retrieved_chunks)
        generated_answer = triple["generated_answer"]

        faithfulness = frozen_judge_faithfulness(generated_answer, context)
        relevancy = frozen_judge_relevancy(triple["ideal_answer"], generated_answer)

        hit_scores.append(compute_hit_at_k(retrieved_ids, triple["ground_truth_chunk_ids"]))
        rr_scores.append(compute_rr(retrieved_ids, triple["ground_truth_chunk_ids"]))
        faithfulness_scores.append(faithfulness)
        relevancy_scores.append(relevancy)
        examples.append(
            ExampleResult(
                id=triple["id"],
                faithfulness=faithfulness,
                answer_relevancy=relevancy,
                ideal_answer=triple["ideal_answer"],
                context=context,
            )
        )

    metrics = RagMetrics(
        hit_at_5=_mean(hit_scores),
        mrr=_mean(rr_scores),
        faithfulness=_mean(faithfulness_scores),
        answer_relevancy=_mean(relevancy_scores),
        count=len(triples),
    )
    return metrics, examples


def compute_agreement(
    examples: list[ExampleResult],
    labels: list[dict[str, Any]],
    thresholds: dict[str, float],
) -> Agreement:
    """Compare frozen-judge pass/fail decisions to human labels on the labeled subset.

    For each (example, dimension) the frozen judge "passes" when its score meets
    the dimension threshold (faithfulness/answer_relevancy). Agreement is the
    fraction of (id, dimension) decisions where judge and human agree.

    Two-sided calibration: a label record may carry an optional
    ``candidate_answer`` that the judge re-scores in place of the golden
    generated answer (against the same question's ideal answer and retrieved
    context). This lets the subset include negative cases (unfaithful or
    irrelevant answers) without altering the 15 golden generated answers.
    """
    by_id = {example.id: example for example in examples}
    matches = 0
    total = 0
    for label in labels:
        example = by_id.get(label["id"])
        if example is None:
            raise ValueError(f"label id {label['id']!r} not present in golden set")
        candidate = label.get("candidate_answer")
        if candidate is not None:
            faithfulness = frozen_judge_faithfulness(candidate, example.context)
            answer_relevancy = frozen_judge_relevancy(example.ideal_answer, candidate)
        else:
            faithfulness = example.faithfulness
            answer_relevancy = example.answer_relevancy
        for dimension, score in (
            ("faithfulness", faithfulness),
            ("answer_relevancy", answer_relevancy),
        ):
            judge_pass = score >= thresholds[dimension]
            human_pass = label[dimension] == "pass"
            total += 1
            if judge_pass == human_pass:
                matches += 1
    return Agreement(score=(matches / total if total else 0.0), matches=matches, total=total)


def retrieve_offline(query: str, corpus: list[Chunk], top_k: int = TOP_K) -> list[Chunk]:
    """Deterministic lexical retrieval over the committed golden corpus.

    Production RAG still uses embeddings + reranking. This offline retriever is
    only the CI fixture runner, making retrieval IDs reproducible without
    hosted embedding/rerank calls.
    """
    query_terms = set(_key_terms(query))
    scored: list[tuple[float, str, Chunk]] = []
    for chunk in corpus:
        chunk_terms = set(_key_terms(chunk.text))
        overlap = len(query_terms & chunk_terms)
        union = len(query_terms | chunk_terms) or 1
        score = overlap / union
        scored.append((score, chunk.id, chunk))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [chunk for score, _, chunk in scored[:top_k] if score > 0]


def print_report(
    metrics: RagMetrics,
    thresholds: dict[str, float],
    agreement: Agreement | None = None,
) -> None:
    print(f"Loaded {metrics.count} golden triples")
    print(
        "Thresholds: "
        f"hit@5 >= {thresholds['hit_at_5']}, "
        f"mrr >= {thresholds['mrr']}, "
        f"faithfulness >= {thresholds['faithfulness']}, "
        f"answer_relevancy >= {thresholds['answer_relevancy']}"
    )
    print("Generation metrics scored by the frozen offline judge rubric (not RAGAS / not an LLM judge).")
    print()
    print(f"hit@5:             {metrics.hit_at_5:.3f}  (threshold: {thresholds['hit_at_5']})")
    print(f"MRR:               {metrics.mrr:.3f}  (threshold: {thresholds['mrr']})")
    print(f"faithfulness:      {metrics.faithfulness:.3f}  (threshold: {thresholds['faithfulness']})")
    print(
        "answer relevancy:  "
        f"{metrics.answer_relevancy:.3f}  (threshold: {thresholds['answer_relevancy']})"
    )
    if agreement is not None:
        judge_threshold = thresholds.get("judge_agreement")
        suffix = (
            f"  (threshold: {judge_threshold})"
            if judge_threshold is not None
            else "  (reported; no threshold)"
        )
        print(
            "judge agreement:   "
            f"{agreement.score:.3f}{suffix}  "
            f"[{agreement.matches}/{agreement.total} hand-label decisions]"
        )


def failures(
    metrics: RagMetrics,
    thresholds: dict[str, float],
    agreement: Agreement | None = None,
) -> list[str]:
    checks = {
        "hit@5": (metrics.hit_at_5, thresholds["hit_at_5"]),
        "MRR": (metrics.mrr, thresholds["mrr"]),
        "faithfulness": (metrics.faithfulness, thresholds["faithfulness"]),
        "answer_relevancy": (metrics.answer_relevancy, thresholds["answer_relevancy"]),
    }
    failed = [
        f"{name} {observed:.3f} < threshold {threshold}"
        for name, (observed, threshold) in checks.items()
        if observed < threshold
    ]
    # Judge agreement is only gated when a hand-labeled subset was evaluated AND
    # a threshold key exists — conservative, never a false failure without labels.
    if agreement is not None and "judge_agreement" in thresholds:
        if agreement.score < thresholds["judge_agreement"]:
            failed.append(
                f"judge_agreement {agreement.score:.3f} < threshold {thresholds['judge_agreement']}"
            )
    return failed


def _validate_golden(triples: list[dict[str, Any]]) -> None:
    if len(triples) != EXPECTED_TRIPLE_COUNT:
        raise ValueError(f"expected {EXPECTED_TRIPLE_COUNT} golden triples, found {len(triples)}")
    required = {"id", "question", "ideal_answer", "generated_answer", "ground_truth_chunk_ids", "ground_truth_chunks"}
    ids: set[str] = set()
    chunk_ids: set[str] = set()
    for row in triples:
        missing = required - row.keys()
        if missing:
            raise ValueError(f"line {row.get('_line')}: missing fields {sorted(missing)}")
        if row["id"] in ids:
            raise ValueError(f"duplicate triple id {row['id']!r}")
        ids.add(row["id"])
        if not row["ground_truth_chunk_ids"]:
            raise ValueError(f"{row['id']}: ground_truth_chunk_ids must not be empty")
        if not row["ground_truth_chunks"]:
            raise ValueError(f"{row['id']}: ground_truth_chunks must not be empty")
        gt_chunk_ids = {chunk["id"] for chunk in row["ground_truth_chunks"]}
        if not set(row["ground_truth_chunk_ids"]) <= gt_chunk_ids:
            raise ValueError(f"{row['id']}: ground_truth_chunk_ids missing matching chunk text")
        for chunk in row["ground_truth_chunks"]:
            if not chunk.get("id") or not chunk.get("text"):
                raise ValueError(f"{row['id']}: every ground_truth_chunk needs id and text")
            if chunk["id"] in chunk_ids:
                raise ValueError(f"duplicate chunk id {chunk['id']!r}")
            chunk_ids.add(chunk["id"])


def _validate_labels(labels: list[dict[str, Any]]) -> None:
    if not labels:
        raise ValueError("hand-label file is empty")
    required = {"id", "faithfulness", "answer_relevancy", "rationale"}
    seen: set[str] = set()
    for row in labels:
        missing = required - row.keys()
        if missing:
            raise ValueError(f"label line {row.get('_line')}: missing fields {sorted(missing)}")
        if row["id"] in seen:
            raise ValueError(f"duplicate label id {row['id']!r}")
        seen.add(row["id"])
        for dimension in ("faithfulness", "answer_relevancy"):
            if row[dimension] not in ("pass", "fail"):
                raise ValueError(
                    f"{row['id']}: {dimension} must be 'pass' or 'fail', got {row[dimension]!r}"
                )
        if "candidate_answer" in row and not (
            isinstance(row["candidate_answer"], str) and row["candidate_answer"].strip()
        ):
            raise ValueError(f"{row['id']}: candidate_answer must be a non-empty string when present")


def _build_corpus(triples: list[dict[str, Any]]) -> list[Chunk]:
    return [
        Chunk(id=chunk["id"], text=chunk["text"])
        for triple in triples
        for chunk in triple["ground_truth_chunks"]
    ]


def _key_terms(text: str) -> list[str]:
    terms = re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*|[a-z0-9]+@[a-z0-9.-]+", text.lower())
    return [term for term in terms if term not in _STOPWORDS and len(term) > 1]


def _coverage(expected_terms: list[str], actual_text: str) -> float:
    expected = set(expected_terms)
    if not expected:
        return 1.0
    actual = set(_key_terms(actual_text))
    return len(expected & actual) / len(expected)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the offline deterministic RAG eval")
    parser.add_argument("--golden", required=True, help="Path to 15-triple golden JSONL")
    parser.add_argument(
        "--labels",
        help="Optional hand-labeled subset JSONL; reports frozen-judge vs human agreement",
    )
    args = parser.parse_args()

    try:
        triples = load_golden(args.golden)
        thresholds = load_thresholds()
        metrics, examples = evaluate_with_examples(triples)
        agreement = None
        if args.labels:
            agreement = compute_agreement(examples, load_labels(args.labels), thresholds)
    except Exception as exc:
        print(f"ERROR: RAG eval could not run: {exc}", file=sys.stderr)
        sys.exit(2)

    print_report(metrics, thresholds, agreement)
    failed = failures(metrics, thresholds, agreement)
    if failed:
        for failure in failed:
            print(f"FAIL: {failure}")
        sys.exit(1)

    print("\nPASS: all metrics meet thresholds")
    sys.exit(0)


if __name__ == "__main__":
    main()
