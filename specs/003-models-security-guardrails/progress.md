# Owner C Progress Tracker

Central status tracker for Models, Security & Guardrails.

## Phase Status

| Phase | Scope | Status |
|---|---|---|
| Phase 0 | Spec drift fixed | DONE |
| Phase 1 | Service auth verified | PASS |
| Phase 2 | Section C spec coverage | PASS |
| Phase 3 | Endpoint aliases verified | PASS |
| Phase 4A | Public dataset + classical baseline | PASS |
| Phase 4B | Classical model served | PASS |
| Phase 4C | Classifier eval gate runner | PASS |
| Phase 4D | DL/ONNX baseline | PASS |
| Phase 4D.5 | OpenTelemetry + Jaeger tracing | PASS |
| Phase 4D.6 | Vault secret inventory + Jaeger readiness | PASS |
| Phase 4E | LLM zero-shot baseline | PASS |
| Phase 5 | Production model decision | PASS |
| Phase 6 | Guardrails + red-team suite | PASS |
| Phase 7 | Redaction hardening / credit-card add-on | PENDING |
| Phase 8 | CI handoff | PENDING |

## Key Artifacts

| Artifact | Path / SHA-256 |
|---|---|
| Processed dataset | `training/intent_classifier/data/customer_support_intents_mapped.jsonl` |
| Dataset SHA-256 | `848697bc0d6f6a2a152a89a83dd00e5123dacdcbff86a6a449f84233e2af64ae` |
| Classical joblib artifact | `training/intent_classifier/artifacts/classical_intent_logreg.joblib` |
| Classical artifact SHA-256 | `9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a` |
| DL/ONNX artifact | `training/intent_classifier/artifacts/dl_intent_mlp.onnx` |
| DL/ONNX artifact SHA-256 | `87203e8f3842d420e92a97a8c017124892063285be543c8dc780c898aa3e35b7` |
| LLM zero-shot metrics | `training/intent_classifier/artifacts/llm_zero_shot_metrics.json` |
| LLM zero-shot predictions | `training/intent_classifier/artifacts/llm_zero_shot_predictions.jsonl` |
| Model card | `modelserver/MODEL_CARD.md` |
| Classifier eval runner | `evals/classifier/run.py` |
| Secret inventory | `docs/SECRETS.md` |
| Red-team fixtures | `evals/redteam_cross_tenant/fixtures/redteam_cases.jsonl` |
| Red-team runner | `evals/redteam_cross_tenant/run.py` |

## Production Model Choice

Phase 5 selected **Classical TF-IDF + LogisticRegression** for production
serving.

- Served artifact: `modelserver/artifacts/classical_intent_logreg.joblib`.
- Training artifact: `training/intent_classifier/artifacts/classical_intent_logreg.joblib`.
- Artifact SHA-256: `9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a`.
- Model version: `classical-intent-logreg-v0.1.0`.
- Challenger: DL/ONNX TF-IDF + MLPClassifier, which has the highest F1 but is
  not yet served.
- LLM routing rejected for production: slower, cost-bearing, provider-dependent,
  and much weaker macro-F1.

Highest F1 did not automatically win. The classical model was selected because
it is already served, very fast, operationally simple, strong enough on F1, and
keeps runtime risk low.

## Current Metrics

All classifier baselines use the same held-out split:
`training/intent_classifier/artifacts/classical_split.json`.

| Baseline | Macro-F1 | faq_rag F1 | lead_capture F1 | human_escalate F1 | spam F1 | other_agent F1 | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Classical TF-IDF + LogisticRegression | `0.971762` | `0.991597` | `0.954733` | `0.950000` | `0.995816` | `0.966667` | `0.0101 ms/item` |
| DL/ONNX TF-IDF + MLPClassifier | `0.9834` | `0.9958` | `0.9712` | `0.9667` | `0.9958` | `0.9874` | `0.0419 ms/item` |
| Gemini zero-shot (`gemini-2.5-flash-lite`) | `0.503639` | `0.471311` | `0.472050` | `0.554974` | `0.987342` | `0.032520` | `1107.26 ms/item` |

LLM zero-shot notes:

- Provider/model: Gemini `gemini-2.5-flash-lite`.
- Prompt version: `intent-zero-shot-v2-balanced-labels`.
- Evaluated count: `600`; failed count: `0`.
- Result is slower and less accurate than both supervised lean baselines.
- Spam detection is strong, but `other_agent` is weak because it is a
  project-specific routing convention rather than a naturally obvious semantic
  category.
- This supports shipping a supervised lean classifier instead of LLM routing.

## Open Risks

- CI is not wired yet.
- Redaction hardening remains Phase 7, especially broader credit-card coverage
  and exception/access-log leak handling.
- Endpoint migration to target names requires Owner B/D coordination.

## Guardrails / Red-Team

- Phase 6 approach: deterministic rules-first platform rails.
- Endpoints implemented: `/guardrails/input`, `/check-input`,
  `/guardrails/output`, `/check-output`.
- Platform rails block prompt injection, jailbreaks, system/developer prompt
  extraction, cross-tenant requests, fake tenant override attempts, tool abuse,
  secret extraction, and attempts to disable guardrails.
- Tenant rails can only narrow behavior with allowed/blocked topics; they cannot
  weaken platform DENY.
- Redaction covers fake API keys/tokens, emails, phones, token-like strings, and
  credit-card-like strings in the guardrails sidecar.
- Red-team fixture path: `evals/redteam_cross_tenant/fixtures/redteam_cases.jsonl`.
- Red-team runner command: `uv run --project guardrails python -m evals.redteam_cross_tenant.run`.
- Pass threshold: root `eval_thresholds.yaml` `redteam.required_pass_rate = 1.00`.

## Tracing

- Tracing backend: OpenTelemetry + Jaeger.
- Jaeger UI: `http://localhost:16686`.
- Services traced: backend, modelserver, guardrails.
- Propagation: W3C trace context plus existing `X-Request-ID`.
- Safety policy: no raw user text, no prompts, no secrets, no Authorization
  headers, no cookies, and no raw PII in custom span attributes.
- Local verification: run `docker compose up --build`, exercise backend calls
  that reach modelserver/guardrails, then open the Jaeger UI.
- Vault note: local Jaeger needs no tracing secret. If an external OTLP backend
  is used later, Owner A injects exporter credentials through env/settings.
- Jaeger config: `JAEGER_UI_BASE_URL=http://localhost:16686` and
  `JAEGER_QUERY_BASE_URL=http://localhost:16686`.
- UI/admin recommendation: show/link trace IDs for admins rather than exposing
  raw Jaeger trace payloads to visitor-facing UI.

## Vault / Secrets

- Vault strategy: Vault is the source of truth; local `.env` fallback is allowed
  for development.
- Owner C secrets: `SERVICE_AUTH_TOKEN`, `GEMINI_API_KEY`, optional
  `GROQ_API_KEY`.
- Modelserver and guardrails consume `SERVICE_AUTH_TOKEN` through env only;
  they do not couple directly to Vault.
- Shared secrets inventoried in `docs/SECRETS.md`: `JWT_SECRET`, tenant widget
  signing keys, `DATABASE_URL` when password-bearing, `POSTGRES_PASSWORD`,
  `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, and `VAULT_TOKEN`.
- Local Jaeger all-in-one does not need a key.
- LLM fallback rule: Gemini is primary; Groq fallback must be a separate
  provider/model run and not mixed into the Gemini metrics file.

## Next Action

Phase 7: redaction hardening / credit-card add-on.
