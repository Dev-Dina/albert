"""Train the offline classical visitor-intent classifier baseline.

Phase 4A only: this script writes an artifact and metrics but does not wire the
artifact into modelserver serving.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "data" / "customer_support_intents_mapped.jsonl"
ARTIFACT_DIR = ROOT / "artifacts"
ARTIFACT_PATH = ARTIFACT_DIR / "classical_intent_logreg.joblib"
METRICS_PATH = ARTIFACT_DIR / "classical_metrics.json"
SPLIT_PATH = ARTIFACT_DIR / "classical_split.json"

RANDOM_SEED = 10
TEST_SIZE = 0.30
LABELS = [
    "faq_rag",
    "lead_capture",
    "human_escalate",
    "spam",
    "other_agent",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_dataset(path: Path) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not {"id", "label", "text"} <= record.keys():
                raise ValueError(f"Missing required key at line {line_number}")
            if record["label"] not in LABELS:
                raise ValueError(f"Unknown label at line {line_number}: {record['label']}")
            records.append(
                {
                    "id": str(record["id"]),
                    "label": str(record["label"]),
                    "text": str(record["text"]),
                }
            )
    seen_ids = {record["id"] for record in records}
    if len(seen_ids) != len(records):
        raise ValueError("Dataset IDs must be unique")
    label_counts = {label: 0 for label in LABELS}
    for record in records:
        label_counts[record["label"]] += 1
    missing = [label for label, count in label_counts.items() if count == 0]
    if missing:
        raise ValueError(f"Dataset missing labels: {missing}")
    return records


def build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    min_df=1,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                LogisticRegression(
                    max_iter=1000,
                    class_weight="balanced",
                    random_state=RANDOM_SEED,
                    solver="lbfgs",
                ),
            ),
        ]
    )


def latency_ms_per_item(model: Pipeline, texts: list[str]) -> float:
    if not texts:
        return 0.0
    repeats = max(1, 100 // len(texts))
    batch = texts * repeats
    start = time.perf_counter()
    model.predict(batch)
    elapsed = time.perf_counter() - start
    return (elapsed / len(batch)) * 1000.0


def per_class_f1(report: dict[str, Any]) -> dict[str, float]:
    return {label: float(report[label]["f1-score"]) for label in LABELS}


def main() -> None:
    records = load_dataset(DATASET_PATH)
    label_distribution = {label: 0 for label in LABELS}
    for record in records:
        label_distribution[record["label"]] += 1
    train_records, test_records = train_test_split(
        records,
        test_size=TEST_SIZE,
        random_state=RANDOM_SEED,
        stratify=[record["label"] for record in records],
    )

    train_texts = [record["text"] for record in train_records]
    train_labels = [record["label"] for record in train_records]
    test_texts = [record["text"] for record in test_records]
    test_labels = [record["label"] for record in test_records]

    model = build_pipeline()
    model.fit(train_texts, train_labels)
    predictions = model.predict(test_texts)

    report = classification_report(
        test_labels,
        predictions,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    macro_f1 = float(f1_score(test_labels, predictions, labels=LABELS, average="macro"))
    latency = latency_ms_per_item(model, test_texts)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, ARTIFACT_PATH)

    dataset_sha256 = sha256_file(DATASET_PATH)
    artifact_sha256 = sha256_file(ARTIFACT_PATH)
    metrics = {
        "model_name": "tfidf_logistic_regression",
        "phase": "4A_repair_classical_baseline",
        "random_seed": RANDOM_SEED,
        "test_size_fraction": TEST_SIZE,
        "dataset_path": str(DATASET_PATH.relative_to(ROOT.parent.parent)),
        "dataset_sha256": dataset_sha256,
        "artifact_path": str(ARTIFACT_PATH.relative_to(ROOT.parent.parent)),
        "artifact_sha256": artifact_sha256,
        "train_size": len(train_records),
        "test_size": len(test_records),
        "label_distribution": label_distribution,
        "labels": LABELS,
        "macro_f1": macro_f1,
        "per_class_f1": per_class_f1(report),
        "classification_report": report,
        "latency_ms_per_item_estimate": latency,
        "notes": [
            "Training data is mapped from public support-style datasets.",
            "Deprecated bootstrap scaffold is retained under examples/bootstrap and is not used.",
            "Artifact is not wired into modelserver serving in Phase 4A.",
            "DL/ONNX and LLM zero-shot baselines are pending.",
        ],
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    split = {
        "random_seed": RANDOM_SEED,
        "test_size_fraction": TEST_SIZE,
        "train_ids": sorted(record["id"] for record in train_records),
        "test_ids": sorted(record["id"] for record in test_records),
    }
    SPLIT_PATH.write_text(json.dumps(split, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"DATASET_SHA256={dataset_sha256}")
    print(f"ARTIFACT={ARTIFACT_PATH}")
    print(f"ARTIFACT_SHA256={artifact_sha256}")
    print(f"MACRO_F1={macro_f1:.4f}")
    print(f"LATENCY_MS_PER_ITEM={latency:.4f}")
    print("PER_CLASS_F1=" + json.dumps(metrics["per_class_f1"], sort_keys=True))


if __name__ == "__main__":
    main()
