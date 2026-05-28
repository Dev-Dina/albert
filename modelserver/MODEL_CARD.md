# Albert Intent Classifier Model Card

## Task

Visitor-intent routing for Albert's modelserver. The classifier predicts one of
five labels from untrusted visitor text so the backend can route safely without
accepting tenant identity from model-facing input.

Production serving uses the offline classical baseline from
`modelserver/artifacts/`.

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
Training artifact:
`training/intent_classifier/artifacts/classical_intent_logreg.joblib`

Served artifact:
`modelserver/artifacts/classical_intent_logreg.joblib`

Artifact SHA-256:
`9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a`

## DL/ONNX Baseline

Status: complete for Phase 4D; evaluated only, not selected as the production
model.

Approach:

- TF-IDF vectorizer
- Small sklearn `MLPClassifier` neural baseline
- Exported to ONNX with `skl2onnx`
- Evaluated with `onnxruntime`
- Reused the exact `train_ids` and `test_ids` from
  `training/intent_classifier/artifacts/classical_split.json`

Metrics:

| Metric | Value |
|---|---|
| Macro-F1 | `0.9834` |
| Test size | `600` |
| Latency estimate | `0.0419 ms/item` |
| Cost | `$0` offline/local inference |

Per-class F1:

| Label | F1 |
|---|---|
| `faq_rag` | `0.9958` |
| `lead_capture` | `0.9712` |
| `human_escalate` | `0.9667` |
| `spam` | `0.9958` |
| `other_agent` | `0.9874` |

Artifact path:
`training/intent_classifier/artifacts/dl_intent_mlp.onnx`

Metrics path:
`training/intent_classifier/artifacts/dl_onnx_metrics.json`

Artifact SHA-256:
`87203e8f3842d420e92a97a8c017124892063285be543c8dc780c898aa3e35b7`

This baseline is not wired into `/classify` in Phase 4D. Runtime serving still
uses the classical artifact.

## LLM Zero-Shot Baseline

Status: complete for Phase 4E; evaluated only, not selected as the production
model.

Approach:

- Provider: Gemini
- Model: `gemini-2.5-flash-lite`
- Prompt version: `intent-zero-shot-v2-balanced-labels`
- Zero-shot only; no examples or fine-tuning
- Reused the same 600-item held-out test split as the classical and DL/ONNX
  baselines

`gemini-2.5-flash-lite` is the official recorded LLM zero-shot baseline for this
submission. Earlier `gemini-2.0-flash` references (planning/config/provider
version) are not this committed artifact; the maintained baseline run uses
`gemini-2.5-flash-lite` (provider model-lifecycle update). CI does not call
Gemini — it consumes the committed metrics/predictions artifacts.

Metrics:

| Metric | Value |
|---|---|
| Macro-F1 | `0.5036` |
| Test size | `600` |
| Failed calls | `0` |
| Latency estimate | `1107.26 ms/item` |
| Cost | Not recorded; token usage captured in metrics |

Per-class F1:

| Label | F1 |
|---|---|
| `faq_rag` | `0.4713` |
| `lead_capture` | `0.4720` |
| `human_escalate` | `0.5550` |
| `spam` | `0.9873` |
| `other_agent` | `0.0325` |

Metrics path:
`training/intent_classifier/artifacts/llm_zero_shot_metrics.json`

Predictions path:
`training/intent_classifier/artifacts/llm_zero_shot_predictions.jsonl`

Observed behavior: the zero-shot LLM performed well on `spam` but poorly on
`other_agent`, often collapsing project-specific routing cases into `faq_rag`.
The likely reason is that `other_agent` is an Albert routing convention rather
than a naturally obvious semantic intent category. This result supports serving
a supervised lean classifier for routing instead of using LLM-per-message
routing.

## Production Choice

Phase 5 production choice: **Classical TF-IDF + LogisticRegression**.

Rationale:

- Strong macro-F1 (`0.9718`) and balanced per-class behavior.
- Fastest measured inference latency (`0.0101 ms/item`).
- Already served by modelserver with artifact SHA-256 verification.
- Lowest serving complexity and operational risk: `scikit-learn` + `joblib`,
  no `torch`, no `transformers`, no GPU, no network call, and no provider key.
- Keeps the serving container lean and failure modes local.

The DL/ONNX baseline has the highest measured macro-F1 (`0.9834`) but does not
automatically win. It remains the challenger because promoting it would require
serving-path hardening, dependency review, and artifact/runtime validation. It
can be promoted later if those operational checks justify the extra complexity.

The Gemini zero-shot baseline is rejected for production routing because it is
slower, provider-dependent, cost-bearing, and much weaker on macro-F1. It also
struggles with `other_agent`, which is a project-specific routing convention
rather than a natural semantic category.

## Same-Test-Set Comparison

| Baseline | Status | Macro-F1 | Test size | Latency | Cost | Artifact / output |
|---|---|---:|---:|---:|---:|---|
| Classical TF-IDF + LogisticRegression | **Production selected** | `0.9718` | `600` | `0.0101 ms/item` | `$0` | `training/intent_classifier/artifacts/classical_intent_logreg.joblib` |
| Small DL sklearn MLP exported to ONNX | Challenger, not served | `0.9834` | `600` | `0.0419 ms/item` | `$0` | `training/intent_classifier/artifacts/dl_intent_mlp.onnx` |
| Gemini zero-shot (`gemini-2.5-flash-lite`) | Evaluated, not selected | `0.5036` | `600` | `1107.26 ms/item` | Token usage captured; dollar cost not recorded | `training/intent_classifier/artifacts/llm_zero_shot_metrics.json` |

## Serving Notes

Modelserver verifies the served artifact SHA-256 at load time. On a mismatch it
fails closed: classification requests return 503 and the mismatched model is not
used. The service may still boot to expose health/error diagnostics (health
reports `loaded: false` with the mismatch error). Runtime dependencies remain
lean: `fastapi`, `uvicorn`, `scikit-learn`, and `joblib`; no `torch` or
`transformers`.
