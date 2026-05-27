# Albert Intent Classifier Model Card

## Task

Visitor-intent routing for Albert's modelserver. The classifier predicts one of
five labels from untrusted visitor text so the backend can route safely without
accepting tenant identity from model-facing input.

Phase 4A-repair creates an offline classical baseline from public support-style
data only. The artifact is not wired into `/classify` yet.

## Labels

| Label | Meaning |
|---|---|
| `faq_rag` | Answerable from tenant CMS content via RAG. |
| `lead_capture` | Visitor wants contact, booking, quote, demo, or sales follow-up. |
| `human_escalate` | Visitor needs a human/support/manager handoff. |
| `spam` | Junk, scam, unrelated marketing, or abusive low-value traffic. |
| `other_agent` | Safe fallback for unrelated or uncertain requests. |

## Threshold Behavior

Starting threshold: `0.70`.

If the top-label confidence is below `0.70`, serving must return
`other_agent`. The classifier request body must not include `tenant_id`.

## Dataset

Processed source:
`training/intent_classifier/data/customer_support_intents_mapped.jsonl`

Original public sources:

- `bitext/Bitext-customer-support-llm-chatbot-training-dataset` from Hugging
  Face, a public customer-service intent dataset. Bitext describes it as hybrid
  synthetic support data for customer-service intent detection.
- UCI SMS Spam Collection, used only as a public spam supplement because the
  Bitext support data does not include a spam/junk class.

Mapping: `training/intent_classifier/label_mapping.yaml`

The deprecated synthetic bootstrap scaffold remains at
`training/intent_classifier/examples/bootstrap/bootstrap_intents.jsonl` only for
review history. It is not the training source and is not used by
`train_classical.py`.

Dataset SHA-256:
`848697bc0d6f6a2a152a89a83dd00e5123dacdcbff86a6a449f84233e2af64ae`

Processed dataset size and distribution:

| Label | Rows |
|---|---:|
| `faq_rag` | 400 |
| `lead_capture` | 400 |
| `human_escalate` | 400 |
| `spam` | 400 |
| `other_agent` | 400 |

Held-out split: fixed stratified split with `random_seed=10` and
`test_size=0.30`; split manifest written to
`training/intent_classifier/artifacts/classical_split.json`.

## Classical ML Baseline

Status: complete for Phase 4A-repair.

Pipeline:

- TF-IDF vectorizer
- LogisticRegression
- Fixed random seed
- Stratified train/test split

Metrics:

| Metric | Value |
|---|---|
| Macro-F1 | `0.9718` |
| Test size | `600` |
| Latency estimate | `0.0101 ms/item` |

Per-class F1:

| Label | F1 |
|---|---|
| `faq_rag` | `0.9916` |
| `lead_capture` | `0.9547` |
| `human_escalate` | `0.9500` |
| `spam` | `0.9958` |
| `other_agent` | `0.9667` |

Artifact path:
`training/intent_classifier/artifacts/classical_intent_logreg.joblib`

Artifact SHA-256:
`9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a`

## DL/ONNX Baseline

Status: pending mandatory Phase 4 follow-up.

Must use the same held-out test set as the classical baseline. Runtime serving
must not add `torch` or `transformers`; any selected DL model ships only as an
exported ONNX artifact.

## LLM Zero-Shot Baseline

Status: pending mandatory Phase 4 follow-up.

Must use the same held-out test set as the classical baseline. Record prompt,
model/provider/version, macro-F1, per-class F1, latency, and cost assumptions.

## Production Choice

Pending. No production classifier choice is made in Phase 4A.

## Serving Notes

The Phase 4A artifact is offline-only and is not loaded by modelserver. Phase 4B
must add serving code, boot-time artifact SHA-256 verification, and `/health`
model metadata without adding `torch` or `transformers` to the runtime image.
