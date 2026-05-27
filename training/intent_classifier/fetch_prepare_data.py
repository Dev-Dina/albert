"""Fetch and map public support-style intent data for the offline classifier.

Downloads the public Bitext customer-support intent dataset and a small public
spam supplement, then writes a balanced five-label JSONL dataset for Albert.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_PATH = ROOT / "data" / "customer_support_intents_mapped.jsonl"
MANIFEST_PATH = ROOT / "data" / "customer_support_intents_manifest.json"

BITEXT_URL = (
    "https://huggingface.co/datasets/bitext/"
    "Bitext-customer-support-llm-chatbot-training-dataset/resolve/main/"
    "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"
)
BITEXT_RAW_PATH = RAW_DIR / "Bitext_Sample_Customer_Support_Training_Dataset_27K_responses-v11.csv"

SMS_SPAM_URL = "https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip"
SMS_SPAM_RAW_PATH = RAW_DIR / "smsspamcollection.zip"

RANDOM_SEED = 42
MAX_EXAMPLES_PER_LABEL = 400
LABELS = ["faq_rag", "lead_capture", "human_escalate", "spam", "other_agent"]

SOURCE_INTENT_TO_LABEL = {
    "check_cancellation_fee": "faq_rag",
    "check_invoice": "faq_rag",
    "check_payment_methods": "faq_rag",
    "check_refund_policy": "faq_rag",
    "delivery_options": "faq_rag",
    "get_invoice": "faq_rag",
    "track_refund": "faq_rag",
    "create_account": "lead_capture",
    "newsletter_subscription": "lead_capture",
    "place_order": "lead_capture",
    "set_up_shipping_address": "lead_capture",
    "cancel_order": "human_escalate",
    "change_order": "human_escalate",
    "complaint": "human_escalate",
    "delete_account": "human_escalate",
    "payment_issue": "human_escalate",
    "change_shipping_address": "other_agent",
    "edit_account": "other_agent",
    "review": "other_agent",
    "switch_account": "other_agent",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            path.write_bytes(response.read())
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"Could not download public dataset from {url}. "
            "Network access may be blocked; no synthetic fallback is used."
        ) from exc


def normalize_text(text: str) -> str:
    return " ".join(text.casefold().split())


def load_bitext_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with BITEXT_RAW_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=1):
            intent = (row.get("intent") or "").strip()
            albert_label = SOURCE_INTENT_TO_LABEL.get(intent)
            instruction = (row.get("instruction") or "").strip()
            if not albert_label or not instruction:
                continue
            records.append(
                {
                    "id": f"bitext_{row_number:05d}",
                    "label": albert_label,
                    "text": instruction,
                    "source_dataset": "bitext_customer_support",
                    "source_intent": intent,
                    "source_category": (row.get("category") or "").strip(),
                }
            )
    return records


def load_spam_records() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    with zipfile.ZipFile(SMS_SPAM_RAW_PATH) as archive:
        with archive.open("SMSSpamCollection") as handle:
            for row_number, raw_line in enumerate(handle, start=1):
                line = raw_line.decode("utf-8", errors="replace").rstrip("\n")
                tag, _, text = line.partition("\t")
                if tag != "spam" or not text.strip():
                    continue
                records.append(
                    {
                        "id": f"uci_sms_spam_{row_number:05d}",
                        "label": "spam",
                        "text": text.strip(),
                        "source_dataset": "uci_sms_spam_collection",
                        "source_intent": "spam",
                        "source_category": "spam",
                    }
                )
    return records


def dedupe(records: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    deduped: list[dict[str, str]] = []
    for record in records:
        key = normalize_text(record["text"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def balanced_sample(records: list[dict[str, str]]) -> list[dict[str, str]]:
    rng = random.Random(RANDOM_SEED)
    by_label: dict[str, list[dict[str, str]]] = defaultdict(list)
    for record in records:
        by_label[record["label"]].append(record)

    sampled: list[dict[str, str]] = []
    for label in LABELS:
        label_records = by_label[label]
        if not label_records:
            raise RuntimeError(f"No records mapped to required label {label!r}")
        rng.shuffle(label_records)
        sampled.extend(label_records[:MAX_EXAMPLES_PER_LABEL])

    rng.shuffle(sampled)
    return sampled


def write_jsonl(records: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    download(BITEXT_URL, BITEXT_RAW_PATH)
    download(SMS_SPAM_URL, SMS_SPAM_RAW_PATH)

    source_records = load_bitext_records() + load_spam_records()
    processed_records = balanced_sample(dedupe(source_records))
    write_jsonl(processed_records, PROCESSED_PATH)

    distribution = Counter(record["label"] for record in processed_records)
    manifest = {
        "processed_dataset_path": str(PROCESSED_PATH.relative_to(ROOT.parent.parent)),
        "processed_dataset_sha256": sha256_file(PROCESSED_PATH),
        "source_datasets": [
            {
                "name": "bitext/Bitext-customer-support-llm-chatbot-training-dataset",
                "url": BITEXT_URL,
                "raw_path": str(BITEXT_RAW_PATH.relative_to(ROOT.parent.parent)),
                "raw_sha256": sha256_file(BITEXT_RAW_PATH),
                "notes": "Public customer-service intent dataset; Bitext describes it as hybrid synthetic support data.",
            },
            {
                "name": "UCI SMS Spam Collection",
                "url": SMS_SPAM_URL,
                "raw_path": str(SMS_SPAM_RAW_PATH.relative_to(ROOT.parent.parent)),
                "raw_sha256": sha256_file(SMS_SPAM_RAW_PATH),
                "notes": "Public spam supplement because Bitext has no spam/junk intent.",
            },
        ],
        "label_distribution": dict(sorted(distribution.items())),
        "label_mapping_path": "training/intent_classifier/label_mapping.yaml",
        "random_seed": RANDOM_SEED,
        "max_examples_per_label": MAX_EXAMPLES_PER_LABEL,
        "dedupe_normalized_text": True,
        "bootstrap_scaffold": "training/intent_classifier/examples/bootstrap/bootstrap_intents.jsonl",
        "bootstrap_scaffold_used_for_training": False,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"PROCESSED_DATASET={PROCESSED_PATH}")
    print(f"PROCESSED_DATASET_SHA256={manifest['processed_dataset_sha256']}")
    print("LABEL_DISTRIBUTION=" + json.dumps(manifest["label_distribution"], sort_keys=True))


if __name__ == "__main__":
    main()
