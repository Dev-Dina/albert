"""Evaluate Gemini zero-shot intent classification on the classical held-out split.

The API key is read only from GEMINI_API_KEY. Predictions intentionally omit raw
message text and store only IDs, labels, latency, text length, and text hash.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
from sklearn.metrics import classification_report, confusion_matrix, f1_score

ROOT = Path(__file__).resolve().parent
DATASET_PATH = ROOT / "data" / "customer_support_intents_mapped.jsonl"
ARTIFACT_DIR = ROOT / "artifacts"
SPLIT_PATH = ARTIFACT_DIR / "classical_split.json"
PREDICTIONS_PATH = ARTIFACT_DIR / "llm_zero_shot_predictions.jsonl"
METRICS_PATH = ARTIFACT_DIR / "llm_zero_shot_metrics.json"

# Official recorded LLM zero-shot baseline for this submission (committed artifact:
# artifacts/llm_zero_shot_metrics.json). Earlier `gemini-2.0-flash` references were
# planning/provider-version references and are NOT the submitted benchmark artifact;
# the maintained baseline run uses `gemini-2.5-flash-lite` (provider model-lifecycle
# update — older experimental/preview model IDs can be superseded). CI does not call
# Gemini; it consumes the committed evaluation artifacts and the model card.
DEFAULT_MODEL = "gemini-2.5-flash-lite"
# --provider project-default pins the official recorded baseline model.
PROJECT_DEFAULT_MODEL = "gemini-2.5-flash-lite"
# Only Gemini is implemented; recorded in metrics/predictions per ADR-007.
PROVIDER_API = "gemini"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
LABELS = ["faq_rag", "lead_capture", "human_escalate", "spam", "other_agent"]
MAX_RETRIES = 2
TIMEOUT_SECONDS = 30.0
PROMPT_VERSION = "intent-zero-shot-v2-balanced-labels"
SAMPLE_SEED = 10


class GeminiEvalError(Exception):
    """Raised for a failed Gemini eval call."""


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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


def label_distribution(records: list[dict[str, Any]], key: str = "label") -> dict[str, int]:
    counts = Counter(str(record.get(key)) for record in records)
    return {label: counts.get(label, 0) for label in LABELS}


def load_test_records(
    dataset_path: Path,
    split_path: Path,
    limit: int | None,
    sample_per_class: int | None,
) -> list[dict[str, str]]:
    records = {record["id"]: record for record in load_jsonl(dataset_path)}
    split = json.loads(split_path.read_text(encoding="utf-8"))
    test_ids = split["test_ids"]
    missing = [record_id for record_id in test_ids if record_id not in records]
    if missing:
        raise ValueError(f"{len(missing)} split IDs are missing from the dataset")
    test_records = [records[record_id] for record_id in test_ids]
    if sample_per_class is not None:
        rng = random.Random(SAMPLE_SEED)
        sampled: list[dict[str, str]] = []
        for label in LABELS:
            label_records = [record for record in test_records if record["label"] == label]
            if len(label_records) < sample_per_class:
                raise ValueError(
                    f"Requested {sample_per_class} examples for {label}, "
                    f"but only {len(label_records)} are in the held-out split"
                )
            sampled.extend(rng.sample(label_records, sample_per_class))
        sampled.sort(key=lambda record: (record["label"], record["id"]))
        return sampled
    return test_records[:limit] if limit else test_records


def load_completed_predictions(path: Path, prompt_version: str, model: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    completed: dict[str, dict[str, Any]] = {}
    mismatched = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("prompt_version") != prompt_version or record.get("model") != model:
                mismatched += 1
                continue
            if record.get("predicted") in LABELS:
                completed[str(record["id"])] = record
    if mismatched:
        print(
            "WARNING: existing predictions include a different prompt_version/model; "
            "they were not reused. Use a separate predictions path or delete partial "
            "predictions before the final run."
        )
    return completed


def build_prompt(message: str) -> str:
    labels = ", ".join(LABELS)
    return (
        "You are a strict visitor-intent router. Classify the message into exactly one label.\n"
        f"The label must be exactly one of: {labels}\n\n"
        "Choose the most specific applicable label using these definitions:\n"
        "- faq_rag: broad default for normal support/how-to/account/order/product/policy/billing/status/help questions that could be answered from company knowledge or support content.\n"
        "- lead_capture: pricing, quote, demo, sales, plan, subscription, purchase, booking, contact-me, or buying intent.\n"
        "- human_escalate: narrow label. Use only for a direct request for a human/person/agent/manager, a serious complaint, an urgent unresolved issue, a refund dispute, a cancellation problem, or legal/safety escalation.\n"
        "- spam: junk, scam, irrelevant promotion, abusive nonsense, or clearly non-genuine traffic.\n"
        "- other_agent: ambiguous, multi-step, unsupported, unrelated, or needs agent reasoning but is not clearly human escalation.\n\n"
        "Important bias rule: do not choose human_escalate for ordinary account, order, invoice, payment-method, delivery, or refund-policy questions unless the message directly asks for a human or shows a dispute/urgent unresolved problem.\n\n"
        "Return exactly one JSON object with this schema:\n"
        '{"label":"one_allowed_label","confidence":0.0}\n'
        "No markdown. No explanation. No extra keys.\n\n"
        f"Message:\n{message}"
    )


def extract_text(response_json: dict[str, Any]) -> str:
    candidates = response_json.get("candidates") or []
    if not candidates:
        raise GeminiEvalError("missing candidates")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts)
    if not text.strip():
        raise GeminiEvalError("empty Gemini response")
    return text.strip()


def parse_prediction(text: str) -> tuple[str, float | None]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    data = json.loads(cleaned)
    label = str(data.get("label", "")).strip()
    if label not in LABELS:
        raise GeminiEvalError(f"invalid label returned: {label!r}")
    confidence_value = data.get("confidence")
    confidence = float(confidence_value) if confidence_value is not None else None
    return label, confidence


async def call_gemini(
    *,
    client: httpx.AsyncClient,
    api_key: str,
    model: str,
    message: str,
) -> tuple[str, float | None, dict[str, Any]]:
    payload = {
        "contents": [{"parts": [{"text": build_prompt(message)}]}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 64,
            "responseMimeType": "application/json",
        },
    }
    url = GEMINI_URL.format(model=model)
    last_error = "unknown error"
    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await client.post(url, params={"key": api_key}, json=payload)
            response.raise_for_status()
            response_json = response.json()
            label, confidence = parse_prediction(extract_text(response_json))
            return label, confidence, response_json.get("usageMetadata", {})
        except Exception as exc:
            last_error = type(exc).__name__
            if attempt >= MAX_RETRIES:
                break
            await asyncio.sleep(0.5 * (attempt + 1))
    raise GeminiEvalError(last_error)


def per_class_f1(report: dict[str, Any]) -> dict[str, float]:
    return {label: float(report[label]["f1-score"]) for label in LABELS}


def build_confusion_matrix(y_true: list[str], y_pred: list[str]) -> dict[str, dict[str, int]]:
    """Confusion matrix as {true_label: {predicted_label: count}}. No raw text."""
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS)
    return {
        true_label: {pred_label: int(matrix[row][col]) for col, pred_label in enumerate(LABELS)}
        for row, true_label in enumerate(LABELS)
    }


def cost_estimate(
    input_tokens: int,
    output_tokens: int,
    input_price_per_1m: float,
    output_price_per_1m: float,
) -> float | None:
    if input_price_per_1m <= 0 and output_price_per_1m <= 0:
        return None
    return (input_tokens / 1_000_000 * input_price_per_1m) + (
        output_tokens / 1_000_000 * output_price_per_1m
    )


async def run_eval(args: argparse.Namespace) -> int:
    if args.limit is not None and args.sample_per_class is not None:
        print("ERROR: use --limit or --sample-per-class, not both.", file=sys.stderr)
        return 2

    if args.provider == "groq":
        print(
            "ERROR: Groq provider is not implemented. ADR-007 keeps Groq as a separate "
            "future fallback run; use --provider gemini for the baseline.",
            file=sys.stderr,
        )
        return 2
    if args.provider == "project-default":
        if args.model != PROJECT_DEFAULT_MODEL:
            print(
                f"NOTE: --provider project-default pins the model to {PROJECT_DEFAULT_MODEL} "
                f"(the app's agent model); ignoring --model {args.model}."
            )
        args.model = PROJECT_DEFAULT_MODEL

    records = load_test_records(args.dataset, args.split, args.limit, args.sample_per_class)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    expected_distribution = label_distribution(records)
    is_partial = len(records) < len(load_test_records(args.dataset, args.split, None, None))
    print(f"PROMPT_VERSION={PROMPT_VERSION}")
    print(f"PARTIAL_RUN={str(is_partial).lower()}")
    print("EVALUATED_LABEL_DISTRIBUTION=" + json.dumps(expected_distribution, sort_keys=True))
    if args.limit is not None:
        print("WARNING: --limit takes the first N held-out examples and may be label-unbalanced.")
    if is_partial:
        print("WARNING: partial dry-run output is not final Phase 4E evidence.")
    if args.predictions.exists() and not args.resume:
        print(
            "WARNING: predictions file exists and will be overwritten. "
            "Use --resume only with matching prompt_version/model."
        )

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print(
            "ERROR: GEMINI_API_KEY is required for the Gemini zero-shot baseline.",
            file=sys.stderr,
        )
        print(
            "Set GEMINI_API_KEY in the environment. Owner A/Vault can inject it later via env/settings.",
            file=sys.stderr,
        )
        return 2

    completed = (
        load_completed_predictions(args.predictions, PROMPT_VERSION, args.model)
        if args.resume
        else {}
    )

    predictions: list[dict[str, Any]] = []
    failed = 0
    total_latency_ms = 0.0
    input_tokens = 0
    output_tokens = 0

    with args.predictions.open("a" if args.resume else "w", encoding="utf-8") as output:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            for index, record in enumerate(records, start=1):
                if record["id"] in completed:
                    prediction = completed[record["id"]]
                    predictions.append(prediction)
                    continue

                start = time.perf_counter()
                try:
                    label, confidence, usage = await call_gemini(
                        client=client,
                        api_key=api_key,
                        model=args.model,
                        message=record["text"],
                    )
                    latency_ms = (time.perf_counter() - start) * 1000.0
                    total_latency_ms += latency_ms
                    input_tokens += int(usage.get("promptTokenCount") or 0)
                    output_tokens += int(usage.get("candidatesTokenCount") or 0)
                    prediction = {
                        "id": record["id"],
                        "expected": record["label"],
                        "predicted": label,
                        "confidence": confidence,
                        "latency_ms": latency_ms,
                        "provider": PROVIDER_API,
                        "model": args.model,
                        "prompt_version": PROMPT_VERSION,
                        "text_length": len(record["text"]),
                        "text_sha256": sha256_text(record["text"]),
                    }
                    predictions.append(prediction)
                    output.write(json.dumps(prediction, sort_keys=True) + "\n")
                    output.flush()
                    print(f"[{index}/{len(records)}] id={record['id']} predicted={label}")
                except GeminiEvalError as exc:
                    failed += 1
                    failure = {
                        "id": record["id"],
                        "expected": record["label"],
                        "predicted": None,
                        "error": str(exc),
                        "provider": PROVIDER_API,
                        "model": args.model,
                        "prompt_version": PROMPT_VERSION,
                        "text_length": len(record["text"]),
                        "text_sha256": sha256_text(record["text"]),
                    }
                    output.write(json.dumps(failure, sort_keys=True) + "\n")
                    output.flush()
                    print(f"[{index}/{len(records)}] id={record['id']} failed={type(exc).__name__}")

    scored = [prediction for prediction in predictions if prediction.get("predicted") in LABELS]
    if not scored:
        print("ERROR: no successful predictions to score", file=sys.stderr)
        return 2

    y_true = [prediction["expected"] for prediction in scored]
    y_pred = [prediction["predicted"] for prediction in scored]
    report = classification_report(
        y_true,
        y_pred,
        labels=LABELS,
        output_dict=True,
        zero_division=0,
    )
    macro_f1 = float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0))
    estimated_cost = cost_estimate(
        input_tokens,
        output_tokens,
        args.input_price_per_1m,
        args.output_price_per_1m,
    )
    latency_ms_per_item = total_latency_ms / max(1, len(scored) - len(completed))
    metrics = {
        "provider": PROVIDER_API,
        "model_name": args.model,
        "prompt_version": PROMPT_VERSION,
        "phase": "4E_llm_zero_shot_baseline",
        "dataset_path": str(args.dataset.relative_to(ROOT.parent.parent)),
        "split_path": str(args.split.relative_to(ROOT.parent.parent)),
        "split_source": "reused exact test_ids from classical_split.json",
        "prediction_path": str(args.predictions.relative_to(ROOT.parent.parent)),
        "evaluated_count": len(scored),
        "failed_count": failed,
        "is_partial": is_partial,
        "sample_per_class": args.sample_per_class,
        "limit": args.limit,
        "evaluated_label_distribution": expected_distribution,
        "predicted_label_distribution": label_distribution(scored, key="predicted"),
        "labels": LABELS,
        "macro_f1": macro_f1,
        "per_class_f1": per_class_f1(report),
        "confusion_matrix": build_confusion_matrix(y_true, y_pred),
        "confusion_matrix_label_order": LABELS,
        "classification_report": report,
        "latency_ms_per_item_estimate": latency_ms_per_item,
        "token_usage": {
            "prompt_tokens": input_tokens,
            "candidate_tokens": output_tokens,
        },
        "cost_estimate_usd": estimated_cost,
        "cost_note": (
            "Set --input-price-per-1m and --output-price-per-1m to record a dollar estimate; "
            "API key is never stored."
            if estimated_cost is None
            else "Estimated from Gemini usageMetadata and CLI token prices."
        ),
        "notes": [
            "Gemini zero-shot baseline; no fine-tuning.",
            "Reads GEMINI_API_KEY only from environment.",
            "Predictions omit raw message text and store text length/hash only.",
            "Partial runs are dry-run evidence only and must not update the model card.",
            "Owner A/Vault can inject GEMINI_API_KEY through env/settings later.",
            "Production model choice remains pending Phase 5.",
        ],
    }
    args.metrics.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"PROVIDER={PROVIDER_API}")
    print(f"MODEL={args.model}")
    print(f"PROMPT_VERSION={PROMPT_VERSION}")
    print(f"PARTIAL_RUN={str(is_partial).lower()}")
    print(f"EVALUATED={len(scored)}")
    print(f"FAILED={failed}")
    print(f"MACRO_F1={macro_f1:.6f}")
    print(f"LATENCY_MS_PER_ITEM={latency_ms_per_item:.2f}")
    print("PER_CLASS_F1=" + json.dumps(metrics["per_class_f1"], sort_keys=True))
    print(f"PREDICTIONS={args.predictions}")
    print(f"METRICS={args.metrics}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Gemini zero-shot intent baseline")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Use the first N held-out examples; cheap but may be label-unbalanced.",
    )
    parser.add_argument(
        "--sample-per-class",
        type=int,
        default=None,
        help="Balanced dry run from the held-out split; N examples per Albert label.",
    )
    parser.add_argument("--resume", action="store_true", help="Reuse completed predictions")
    parser.add_argument(
        "--provider",
        choices=["gemini", "project-default", "groq"],
        default="gemini",
        help=(
            "API provider. 'gemini' (default) uses --model. 'project-default' pins "
            "the official recorded baseline (gemini-2.5-flash-lite). 'groq' is a "
            "documented future fallback (ADR-007) and is not implemented."
        ),
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Gemini model name")
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--split", type=Path, default=SPLIT_PATH)
    parser.add_argument("--predictions", type=Path, default=PREDICTIONS_PATH)
    parser.add_argument("--metrics", type=Path, default=METRICS_PATH)
    parser.add_argument("--input-price-per-1m", type=float, default=0.0)
    parser.add_argument("--output-price-per-1m", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    sys.exit(asyncio.run(run_eval(parse_args())))


if __name__ == "__main__":
    main()
