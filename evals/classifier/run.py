"""Offline classifier eval gate for Owner C.

Usage:
    uv run --project modelserver python -m evals.classifier.run

Exit codes:
    0: macro-F1 meets the root eval_thresholds.yaml classifier gate
    1: macro-F1 is below the configured threshold
    2: runner/config/input error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import joblib
from sklearn.metrics import classification_report, f1_score

LABELS = ["faq_rag", "lead_capture", "human_escalate", "spam", "other_agent"]


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "eval_thresholds.yaml").exists() and (parent / "CLAUDE.md").exists():
            return parent
    raise FileNotFoundError("Could not locate repo root eval_thresholds.yaml")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_classifier_threshold(path: Path) -> float:
    """Read classifier.macro_f1_min from the root threshold file.

    This intentionally avoids PyYAML so the eval gate can run with only the
    modelserver's lean runtime/dev dependencies.
    """
    section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if not raw_line.startswith((" ", "\t")) and line.endswith(":"):
            section = line[:-1].strip()
            continue
        if section == "classifier":
            key, separator, value = line.strip().partition(":")
            if separator and key.strip() == "macro_f1_min":
                return float(value.strip())
    raise KeyError(f"missing classifier.macro_f1_min in {path}")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                records.append(json.loads(line))
    return records


def evaluate(dataset_path: Path, split_path: Path, artifact_path: Path) -> dict[str, Any]:
    records = {record["id"]: record for record in load_jsonl(dataset_path)}
    split = json.loads(split_path.read_text(encoding="utf-8"))
    test_ids = split["test_ids"]
    missing_ids = [record_id for record_id in test_ids if record_id not in records]
    if missing_ids:
        raise ValueError(f"{len(missing_ids)} split test ids are missing from dataset")

    test_records = [records[record_id] for record_id in test_ids]
    y_true = [record["label"] for record in test_records]
    texts = [record["text"] for record in test_records]

    model = joblib.load(artifact_path)
    y_pred = model.predict(texts)
    macro_f1 = f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)
    report = classification_report(
        y_true,
        y_pred,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    per_class_f1 = {label: float(report[label]["f1-score"]) for label in LABELS}

    return {
        "artifact_sha256": sha256_file(artifact_path),
        "macro_f1": float(macro_f1),
        "per_class_f1": per_class_f1,
        "test_size": len(test_records),
    }


def print_report(
    result: dict[str, Any],
    threshold: float,
    threshold_path: Path,
    dataset_path: Path,
    split_path: Path,
    artifact_path: Path,
) -> None:
    status = "PASS" if result["macro_f1"] >= threshold else "FAIL"
    print("Classifier eval gate")
    print("=" * 60)
    print(f"threshold_source: {threshold_path}")
    print(f"dataset:          {dataset_path}")
    print(f"split:            {split_path}")
    print(f"artifact:         {artifact_path}")
    print(f"artifact_sha256:  {result['artifact_sha256']}")
    print(f"test_size:        {result['test_size']}")
    print()
    print(f"macro_f1:         {result['macro_f1']:.6f}")
    print(f"threshold:        {threshold:.6f}")
    print()
    print("per_class_f1:")
    for label in LABELS:
        print(f"  {label:<16} {result['per_class_f1'][label]:.6f}")
    print()
    print(
        "GATE=classifier "
        f"STATUS={status.lower()} "
        f"OBSERVED={result['macro_f1']:.6f} "
        f"THRESHOLD={threshold:.6f}"
    )


def parse_args() -> argparse.Namespace:
    root = repo_root()
    default_training = root / "training" / "intent_classifier"
    parser = argparse.ArgumentParser(description="Run the Owner C classifier eval gate")
    parser.add_argument(
        "--thresholds",
        type=Path,
        default=root / "eval_thresholds.yaml",
        help="Root eval_thresholds.yaml path; Owner C must not use evals/eval_thresholds.yaml.",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=default_training / "data" / "customer_support_intents_mapped.jsonl",
    )
    parser.add_argument(
        "--split",
        type=Path,
        default=default_training / "artifacts" / "classical_split.json",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        default=default_training / "artifacts" / "classical_intent_logreg.joblib",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        threshold = load_classifier_threshold(args.thresholds)
        result = evaluate(args.dataset, args.split, args.artifact)
        print_report(result, threshold, args.thresholds, args.dataset, args.split, args.artifact)
    except Exception as exc:
        print(f"ERROR: classifier eval could not run: {exc}", file=sys.stderr)
        return 2
    return 0 if result["macro_f1"] >= threshold else 1


if __name__ == "__main__":
    sys.exit(main())
