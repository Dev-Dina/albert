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
