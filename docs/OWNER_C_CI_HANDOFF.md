# Owner C CI Handoff

Owner C: Models, Security & Guardrails.

This document is the CI handoff for Owner D. It records the exact commands,
thresholds, and expected outputs for the Owner C gates. GitHub Actions wiring is
Owner D work; Owner C does not edit `.github/workflows/*` in Phase 8.

## Threshold Source

Owner C gates read the repository root `eval_thresholds.yaml`.

Do not use `evals/eval_thresholds.yaml` for Owner C gates.

| Gate | Threshold key | Required value |
|---|---|---:|
| Classifier | `classifier.macro_f1_min` | `0.60` |
| Red-team | `redteam.required_pass_rate` | `1.00` |
| Redaction | `redaction.required_pass_rate` | `1.00` |

## Gate Commands

Run from the repository root.

### Classifier

```powershell
uv run --project modelserver python -m evals.classifier.run
```

Expected final line:

```text
GATE=classifier STATUS=pass OBSERVED=<macro-f1> THRESHOLD=0.600000
```

Current observed macro-F1: `0.971762`.

### Red-Team

```powershell
uv run --project guardrails python -m evals.redteam_cross_tenant.run
```

Expected final line:

```text
GATE=redteam_cross_tenant STATUS=pass OBSERVED=1.000000 THRESHOLD=1.000000
```

### Redaction

```powershell
uv run --project guardrails python -m evals.redaction.run
```

Expected final line:

```text
GATE=redaction STATUS=pass OBSERVED=1.000000 THRESHOLD=1.000000 PASS=11 FAIL=0
```

## Service Tests

### Modelserver

```powershell
cd modelserver
uv run python -m pytest tests/test_auth.py tests/test_aliases.py tests/test_health.py tests/test_classifier.py tests/test_tracing.py -q
```

Covers service auth, endpoint aliases, health metadata, classifier behavior,
artifact hash loading behavior, and trace safety.

### Guardrails

```powershell
cd guardrails
uv run python -m pytest tests/test_auth.py tests/test_aliases.py tests/test_health.py tests/test_rails.py tests/test_tracing.py -q
```

Covers service auth, endpoint aliases, health, deterministic platform rails,
tenant rails not weakening platform rails, redaction, and trace safety.

### Backend Owner C Compatibility

```powershell
cd backend
uv run python -m pytest tests/test_redaction.py tests/test_tracing.py tests/test_request_context.py tests/test_inference_client.py -q
```

Covers backend redaction, tracing safety, request ID propagation, and backend
client service auth / `X-Request-ID` behavior.

## Ruff Commands

Run from each service directory:

```powershell
cd backend
uv run python -m ruff check app/core/redaction.py app/core/tracing.py tests/test_redaction.py tests/test_tracing.py
```

```powershell
cd modelserver
uv run python -m ruff check app/redaction.py app/tracing.py app/main.py tests/test_tracing.py
```

```powershell
cd guardrails
uv run python -m ruff check app/redaction.py app/tracing.py app/main.py app/rails.py tests/test_rails.py tests/test_tracing.py
```

Run from repo root for eval runners:

```powershell
uv run --project guardrails python -m ruff check evals/redteam_cross_tenant/run.py evals/redaction/run.py
```

## Generated Artifacts

- Root `artifacts/` is generated local/CI output and is ignored.
- Eval runners print to stdout by default.
- Optional JSON output is only written when `--output <path>` is passed.
- CI may use `--output artifacts/ci-gate-results.json` if Owner D wants a JSONL
  summary.
- Do not commit `artifacts/ci-gate-results.json`.
- Do not remove or ignore `training/intent_classifier/artifacts/` or
  `modelserver/artifacts/`; those are model artifacts, not generated CI output.

## Secrets

- CI must not print `GEMINI_API_KEY`, `GROQ_API_KEY`, `SERVICE_AUTH_TOKEN`,
  Vault tokens, Authorization headers, cookies, API keys, or bearer tokens.
- Phase 8 does not need Gemini or Groq API calls.
- The LLM zero-shot baseline artifacts already exist for review; CI should not
  rerun Gemini.
- Modelserver and guardrails consume `SERVICE_AUTH_TOKEN` through env/settings.
  Owner A/Vault can inject the same value later without direct Vault coupling in
  the sidecars.

## Final Submission Values

| Baseline | Macro-F1 | Latency |
|---|---:|---:|
| Classical TF-IDF + LogisticRegression | `0.971762` | `0.0101 ms/item` |
| DL/ONNX TF-IDF + MLPClassifier | `0.9834` | `0.0419 ms/item` |
| Gemini zero-shot (`gemini-2.5-flash-lite`) | `0.503639` | `1107.26 ms/item` |

- Official recorded LLM baseline: `gemini-2.5-flash-lite` (precomputed, committed
  artifacts). Earlier `gemini-2.0-flash` references were planning/provider-version
  references, not the submitted artifact (provider model-lifecycle update). CI does
  not call Gemini; it consumes committed artifacts and the model card.
- Shipped classifier: Classical TF-IDF + LogisticRegression.
- Challenger: DL/ONNX TF-IDF + MLPClassifier.
- LLM routing rejected for production: slower, provider-dependent,
  cost-bearing, and much weaker macro-F1.
- Tracing backend: OpenTelemetry + Jaeger.
- Service-to-service auth: `Authorization: Bearer <service credential>` with
  local `SERVICE_AUTH_TOKEN` fallback and Vault/env injection later.
- Guardrails sidecar: deterministic rules-first platform rails; tenant rails
  may narrow behavior but cannot weaken platform rails.
