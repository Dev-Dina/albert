# Intent Classifier Training

Offline-only training area for the Owner C visitor-intent classifier.

This directory is not part of the modelserver runtime image. It may use training
dependencies such as `scikit-learn` and `joblib`; serving dependencies stay in
`modelserver/pyproject.toml`.

## Public Support Dataset

The current training source is `data/customer_support_intents_mapped.jsonl`,
prepared by `fetch_prepare_data.py` from:

- `bitext/Bitext-customer-support-llm-chatbot-training-dataset`
- UCI SMS Spam Collection, used only as a spam supplement because Bitext has no
  spam/junk intent

The mapping from source intents to Albert's five labels is documented in
`label_mapping.yaml`.

The processed dataset contains the five accepted labels:

- `faq_rag`
- `lead_capture`
- `human_escalate`
- `spam`
- `other_agent`

It is public support-style intent data, not tenant CMS content and not
production Albert conversation data.

Current prepared dataset size: 2,000 rows, balanced at 400 examples per Albert
label. The processed dataset SHA-256 is recorded in
`data/customer_support_intents_manifest.json` and in `modelserver/MODEL_CARD.md`.

## Deprecated Bootstrap Scaffold

`examples/bootstrap/bootstrap_intents.jsonl` is retained only as the deprecated
synthetic scaffold from the first Phase 4A pass. It is not used by
`fetch_prepare_data.py` or `train_classical.py`.

## Fetch / Prepare

```powershell
uv run --project training/intent_classifier python training/intent_classifier/fetch_prepare_data.py
```

If network access to the public datasets is unavailable and raw files are not
already present under `data/raw/`, the script fails instead of falling back to
synthetic data.

## Train

```powershell
uv run --project training/intent_classifier python training/intent_classifier/train_classical.py
```

The script uses a fixed random seed, a stratified leakage-free train/test split,
TF-IDF features, and LogisticRegression. It writes the artifact and metrics under
`training/intent_classifier/artifacts/`.

Phase 4A does not wire the artifact into `/classify`; serving integration is a
later phase.

## LLM Zero-Shot Eval

The official recorded LLM zero-shot baseline for this submission is
**`gemini-2.5-flash-lite`**, evaluated on the **full held-out split** (600
examples, the exact `test_ids` from `classical_split.json`). Earlier references to
`gemini-2.0-flash` or experimental/preview Gemini 2.0 variants were
planning/provider-version references and are **not** the submitted benchmark
artifact. This migration follows provider model-lifecycle realities: older
experimental/preview model IDs can be superseded or shut down, so the committed
baseline records the maintained Gemini 2.5 Flash Lite run. CI does not call Gemini;
it uses committed evaluation artifacts and the model card.

The shipped production classifier remains the **classical TF-IDF + Logistic
Regression** model, not Gemini. Gemini was used only as an LLM baseline comparison
and was rejected for serving (lower quality, higher cost/latency, provider
dependency).

Set `GEMINI_API_KEY` in the environment first (Owner A/Vault inject it outside
local dev). The key is never logged, traced, or written to metrics; predictions
store only text length + SHA-256, never raw message text.

Balanced diagnostic dry run (50 examples, 10 per label) with the official model:

```powershell
uv run --project training/intent_classifier python training/intent_classifier/evaluate_llm_zero_shot.py --provider project-default --sample-per-class 10 --predictions training/intent_classifier/artifacts/llm_zs_flashlite_balanced50_predictions.jsonl --metrics training/intent_classifier/artifacts/llm_zs_flashlite_balanced50_metrics.json
```

Official full held-out run (600 examples, writes the canonical metrics file):

```powershell
uv run --project training/intent_classifier python training/intent_classifier/evaluate_llm_zero_shot.py --provider project-default
```

Add `--input-price-per-1m <usd> --output-price-per-1m <usd>` to record a dollar
cost estimate. Use `--resume` to continue an interrupted full run (matching
`prompt_version` + model only).

Notes:

- `--provider project-default` pins the official recorded baseline
  (`gemini-2.5-flash-lite`). `--provider gemini --model <name>` evaluates a
  specific Gemini model. `--provider groq` is a documented future fallback
  (ADR-007) and is **not implemented**.
- `--sample-per-class N` is a balanced dry run; `--limit N` takes the first N
  held-out examples and may be label-unbalanced. **Partial runs are diagnostics
  only and must not update `MODEL_CARD.md`.**
- The 50-example balanced run is a **diagnostic only** (a subset, not the full
  600-item split), not the official baseline.
- Each run records `provider`, `model_name`, `prompt_version`, evaluated/predicted
  label distributions, a confusion matrix, macro-F1, per-class F1, latency, and
  cost in the metrics file.
