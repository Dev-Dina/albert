"""Train and export the mandatory small DL/ONNX intent baseline.

This is an offline training/eval script only. It reuses the exact held-out test
IDs from the classical baseline split and does not change modelserver serving.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from skl2onnx import convert_sklearn
from skl2onnx.common.data_types import StringTensorType
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report, f1_score
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import Pipeline

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "data" / "customer_support_intents_mapped.jsonl"
ARTIFACT_DIR = ROOT / "artifacts"
SPLIT_PATH = ARTIFACT_DIR / "classical_split.json"
ONNX_PATH = ARTIFACT_DIR / "dl_intent_mlp.onnx"
METRICS_PATH = ARTIFACT_DIR / "dl_onnx_metrics.json"
PREDICTIONS_PATH = ARTIFACT_DIR / "dl_onnx_predictions.jsonl"

RANDOM_SEED = 10
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


def load_jsonl(path: Path) -> list[dict[str, str]]:
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
    return records


def load_split(path: Path, records: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    split = json.loads(path.read_text(encoding="utf-8"))
    by_id = {record["id"]: record for record in records}
    train_ids = split["train_ids"]
    test_ids = split["test_ids"]
    missing = [record_id for record_id in [*train_ids, *test_ids] if record_id not in by_id]
    if missing:
        raise ValueError(f"{len(missing)} split IDs are missing from the dataset")
    return [by_id[record_id] for record_id in train_ids], [by_id[record_id] for record_id in test_ids], split


def build_pipeline() -> Pipeline:
    return Pipeline(
        steps=[
            (
                "tfidf",
                TfidfVectorizer(
                    lowercase=True,
                    ngram_range=(1, 2),
                    max_features=5000,
                    sublinear_tf=True,
                ),
            ),
            (
                "classifier",
                MLPClassifier(
                    hidden_layer_sizes=(64,),
                    activation="relu",
                    solver="adam",
                    alpha=0.0001,
                    batch_size=64,
                    learning_rate_init=0.001,
                    max_iter=120,
                    early_stopping=False,
                    n_iter_no_change=8,
                    random_state=RANDOM_SEED,
                ),
            ),
        ]
    )


def export_onnx(model: Pipeline, path: Path) -> None:
    onnx_model = convert_sklearn(
        model,
        initial_types=[("text_input", StringTensorType([None, 1]))],
        options={id(model.named_steps["classifier"]): {"zipmap": False}},
        target_opset=15,
    )
    path.write_bytes(onnx_model.SerializeToString())


def predict_onnx(path: Path, texts: list[str]) -> list[str]:
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    output_names = [output.name for output in session.get_outputs()]
    outputs = session.run(output_names, {input_name: np.asarray(texts, dtype=object).reshape((-1, 1))})
    labels = outputs[0]
    return [str(label) for label in labels.tolist()]


def latency_ms_per_item(path: Path, texts: list[str]) -> float:
    if not texts:
        return 0.0
    session = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    input_name = session.get_inputs()[0].name
    batch = np.asarray(texts, dtype=object).reshape((-1, 1))
    start = time.perf_counter()
    session.run(None, {input_name: batch})
    elapsed = time.perf_counter() - start
    return (elapsed / len(texts)) * 1000.0


def per_class_f1(report: dict[str, Any]) -> dict[str, float]:
    return {label: float(report[label]["f1-score"]) for label in LABELS}


def main() -> None:
    records = load_jsonl(DATASET_PATH)
    train_records, test_records, split = load_split(SPLIT_PATH, records)
    train_texts = [record["text"] for record in train_records]
    train_labels = [record["label"] for record in train_records]
    test_texts = [record["text"] for record in test_records]
    test_labels = [record["label"] for record in test_records]

    model = build_pipeline()
    model.fit(train_texts, train_labels)

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    export_onnx(model, ONNX_PATH)

    predictions = predict_onnx(ONNX_PATH, test_texts)
    report = classification_report(
        test_labels,
        predictions,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    macro_f1 = float(f1_score(test_labels, predictions, labels=LABELS, average="macro"))
    latency = latency_ms_per_item(ONNX_PATH, test_texts)
    artifact_sha256 = sha256_file(ONNX_PATH)

    metrics = {
        "model_name": "tfidf_mlpclassifier_onnx",
        "phase": "4D_dl_onnx_baseline",
        "random_seed": RANDOM_SEED,
        "split_path": str(SPLIT_PATH.relative_to(ROOT.parent.parent)),
        "split_source": "reused exact train_ids/test_ids from classical_split.json",
        "dataset_path": str(DATASET_PATH.relative_to(ROOT.parent.parent)),
        "dataset_sha256": sha256_file(DATASET_PATH),
        "artifact_path": str(ONNX_PATH.relative_to(ROOT.parent.parent)),
        "artifact_sha256": artifact_sha256,
        "train_size": len(train_records),
        "test_size": len(test_records),
        "labels": LABELS,
        "macro_f1": macro_f1,
        "per_class_f1": per_class_f1(report),
        "classification_report": report,
        "latency_ms_per_item_estimate": latency,
        "onnxruntime_providers": ort.get_available_providers(),
        "split_random_seed": split.get("random_seed"),
        "notes": [
            "Offline mandatory DL/ONNX baseline only.",
            "Not selected as the production model in Phase 4D.",
            "Not wired into modelserver serving.",
            "Uses sklearn MLPClassifier exported to ONNX; no torch or transformers.",
        ],
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with PREDICTIONS_PATH.open("w", encoding="utf-8") as handle:
        for record, predicted in zip(test_records, predictions, strict=True):
            handle.write(
                json.dumps(
                    {
                        "id": record["id"],
                        "expected": record["label"],
                        "predicted": predicted,
                    },
                    sort_keys=True,
                )
                + "\n"
            )

    print(f"ARTIFACT={ONNX_PATH}")
    print(f"ARTIFACT_SHA256={artifact_sha256}")
    print(f"MACRO_F1={macro_f1:.4f}")
    print(f"LATENCY_MS_PER_ITEM={latency:.4f}")
    print(f"TEST_SIZE={len(test_records)}")
    print("PER_CLASS_F1=" + json.dumps(metrics["per_class_f1"], sort_keys=True))


if __name__ == "__main__":
    main()
