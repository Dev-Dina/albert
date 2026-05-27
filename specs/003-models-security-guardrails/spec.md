# Feature 003 — Model Safety & Guardrails

**Status**: In progress
**Owner**: Dina — Owner C: Models, Security & Guardrails
**Branch**: Dina's single Owner C branch — all Owner C Spec Kit artifacts live in this one folder/branch.

**Upstream / normative source**: [`specs/models_security_guardrails_SPEC.md`](../models_security_guardrails_SPEC.md) (the team-aligned Owner C contract). This feature folder does **not** restate that spec — it tracks Dina's slice in Spec-Kit form and references the upstream spec for the full contracts and decisions (O-1…O-8).

Other normative upstream specs (inherited as hard constraints):
- [`specs/tenant_model.md`](../tenant_model.md) — `tenant_id` is the isolation boundary, only from verified context.
- [`specs/role_model.md`](../role_model.md) — `tenant_admin` owns tenant rails; three fixed roles.
- [`specs/agent_tool_contracts.md`](../agent_tool_contracts.md) — model-facing input never carries `tenant_id`.
- CI eval-gate contract: [`specs/001-widget-auth-admin-cicd/contracts/ci-gate.contract.md`](../001-widget-auth-admin-cicd/contracts/ci-gate.contract.md) — the `evals/<gate>/run.py` runner contract Dina's eval harnesses must satisfy.

---

## 1. Summary

Deliver the Model Safety & Guardrails slice (Dina — Owner C) that lets Albert reason over untrusted visitor input without breaking tenant isolation: a lean classifier service, a guardrails sidecar (platform + tenant rails), deterministic redaction, internal service-to-service auth, end-to-end request tracing, and a red-team CI gate. Service-to-service auth and redaction + request-id tracing are **implemented and merged**; the remainder is planned in the workstreams below.

## 2. Scope

In scope (Dina — Owner C): `modelserver/`, `guardrails/`, the backend `inference_client`, backend redaction/request-context utilities, Owner C evals (`classifier`, `redteam_cross_tenant`, `redaction`), and the Owner C portions of the canonical root [`eval_thresholds.yaml`](../../eval_thresholds.yaml).

Out of scope: tenant DB schema / RLS plumbing (Owner A), agent/router and tool implementations (Owner B), admin UI and the CI workflow file wiring (Owner D), and any endpoint **rename/removal** (only additive aliases — see workstream 3).

## 3. Owner C workstreams

Dina's section divides into seven workstreams. (Functional-requirement IDs `FR-C##` are referenced for traceability; full rationale stays in the upstream root SPEC.)

### Workstream 1 — Service-to-service auth · **status: done and merged** ✅
- `API → modelserver` and `API → guardrails` require `Authorization: Bearer <service credential>`.
- Credential is Vault-backed when Owner A's path is ready, with `SERVICE_AUTH_TOKEN` env fallback for local/dev.
- `/health` endpoints remain **public**.
- Verification uses `hmac.compare_digest`; missing/malformed/wrong/unset ⇒ **fail-closed 401**.
- *FR-C01/FR-C02. Delivered by `modelserver/app/auth.py`, `guardrails/app/auth.py`, each `app/main.py`, `backend/app/clients/inference_client.py`.*

### Workstream 2 — Redaction + request tracing · **status: done and merged** ✅
- Deterministic regex redaction (emails, phone, token-like, API-key shapes, Bearer, secret assignments) before logs/traces; counts/types only, never raw values; fail-closed to `[REDACTED]`.
- `request_id` generated at the edge / safe inbound `X-Request-ID` reused; propagated to modelserver/guardrails via `X-Request-ID`.
- Fake-secret leak prevention proven by test.
- **Known follow-ups (tracked, not yet done):** credit-card detector (root SPEC §7 lists it; not in the Phase-2 detector set); exception-traceback redaction (filter covers the message, not `exc_info`); uvicorn access logs sit outside the app filter.
- *FR-C03/FR-C04. Delivered by `backend/app/core/redaction.py`, `backend/app/core/request_context.py`, `inference_client.py`, `backend/app/main.py` wiring.*

### Workstream 3 — Endpoint contracts and aliases · **status: planned**
- Add `/classify` while **keeping** `/predict`.
- Add `/guardrails/input` and `/guardrails/output` while **keeping** `/check-input` and `/check-output`.
- Additive only — **no caller migration without Owner B and Owner D** sign-off.
- *FR-C05. See [`contracts/modelserver-api.md`](./contracts/modelserver-api.md), [`contracts/guardrails-api.md`](./contracts/guardrails-api.md).*

### Workstream 4 — Classifier dataset, training, model card · **status: planned**
- Labels: `faq_rag`, `lead_capture`, `human_escalate`, `spam`, `other_agent`.
- Dataset selection with recorded source + SHA-256.
- Offline training: TF-IDF + LogisticRegression / LinearSVC → `.joblib` artifact (serving stays lean).
- Required comparison baselines before production choice: classical ML (TF-IDF + LogisticRegression or LinearSVC), DL exported to ONNX and served via onnxruntime, and an offline LLM zero-shot baseline. All baselines use the same held-out test set.
- `modelserver/MODEL_CARD.md`: task, dataset source + SHA-256, held-out split identity, per-baseline macro-F1/per-class F1/latency/cost/artifact-size/dependency impact, production-model rationale, served artifact SHA-256.
- Artifact SHA-256 verification at boot (mismatch ⇒ refuse to serve); `/health` reports `model_version`, `artifact_sha256`, `loaded`.
- Confidence behavior: `< 0.70` ⇒ `other_agent` (abstain).
- *FR-C06/FR-C07/FR-C08/FR-C09/FR-C10.*

### Workstream 5 — Guardrails sidecar and tenant/platform rails · **status: planned**
- Platform rails mandatory and always-on: prompt injection, jailbreak, cross-tenant extraction, system-prompt-leak, PII/secret redaction.
- Tenant rails configurable by `tenant_admin` (own tenant) but **cannot weaken** platform rails — a platform DENY overrides any tenant ALLOW; tenant rails may only narrow. Reuse `backend/app/services/guardrail_floor.py` + `guardrails/app/platform_floor.yaml`.
- Guardrail request/response shape is pinned in [`contracts/guardrails-api.md`](./contracts/guardrails-api.md): request text plus optional server-injected context; response `allowed`, `action`, `categories`, `redacted_text`, `reason`.
- Stable categories include `prompt_injection`, `jailbreak`, `cross_tenant`, `system_prompt_extraction`, `tenant_id_override`, `tool_abuse`, `pii`, `secret`, and `credit_card`.
- *FR-C11.*

### Workstream 6 — Red-team + redaction eval gates · **status: planned**
- Red-team categories (root SPEC §10): prompt injection, jailbreak, cross-tenant extraction, system-prompt extraction, fake `tenant_id` override, tool abuse, redaction leak.
- Redaction-leak suite.
- Pass-rate target **1.00** for `redteam` and `redaction`.
- Fixture schemas, local commands, output format, and redaction leak expectations are pinned in [`contracts/redteam-eval.md`](./contracts/redteam-eval.md).
- Harnesses conform to the existing [`001` CI-gate contract](../001-widget-auth-admin-cicd/contracts/ci-gate.contract.md); wiring into `ci.yml` coordinated with Owner D.
- *FR-C12/FR-C13.*

### Workstream 7 — Redaction hardening · **status: planned**
- Required redaction types: fake API keys; Gemini/OpenAI/Groq-style API keys; Bearer tokens; service auth tokens; JWT-like strings; emails; phones; credit-card-like strings; and generic long token-like strings.
- Leak surfaces: backend logs, guardrails logs, modelserver logs, exception tracebacks, HTTP error responses where applicable, OpenTelemetry span attributes, access logs, guardrails responses, eval runner output, and generated CI artifacts.
- Redaction-before-trace/log rule: raw user text, raw prompts, system prompts, Authorization headers, cookies, API keys, service tokens, and raw PII/secrets must never be logged or traced. If user content must be represented, use length, hash, redaction type/count, or high-level category only.
- Eval strategy: separate `evals/redaction/run.py` gate using root `eval_thresholds.yaml` `redaction.required_pass_rate = 1.00`; red-team keeps attack probes, redaction has its own planted-value leak suite.
- Generated artifact rule: root `artifacts/` is generated local/CI output and should not be committed; eval runners print to stdout by default and write JSON only with optional `--output`; `training/intent_classifier/artifacts/` and `modelserver/artifacts/` are model artifacts and must not be deleted/ignored by this phase.

## 4. Cross-owner dependencies

- **Owner A** — Vault runtime injection of the service credential (Owner C uses the `SERVICE_AUTH_TOKEN` env fallback until ready); verified tenant context (`app.tenant_id` RLS session variable) that Owner C must never bypass.
- **Owner B** — classifier/router integration (the router consumes the five labels); **endpoint migration timing** (when callers move onto `/classify` etc.) is Owner B's call. Owner C only adds aliases (workstream 3).
- **Owner D** — CI eval-gate wiring in `.github/workflows/ci.yml` (protected) and the admin UI surface for tenant guardrail-config display/editing.

## 5. Safety constraints (non-negotiable)

- **No `torch` / `transformers` in runtime containers.** DL work is offline; only an exported lean artifact ships. A CI check should assert serving lockfiles stay clean.
- **`tenant_id` never from untrusted input** — not from request body, query params, frontend, or model/LLM output. Model-facing classifier/guardrail input carries no `tenant_id`.
- **Service auth is internal service identity, not tenant identity.** A valid service token authorizes a service call; it never establishes which tenant a request belongs to. Tenant identity comes only from verified auth/session/widget context (Owner A).
- **Tenant rails cannot weaken platform rails.** Platform DENY overrides tenant ALLOW; tenant config may only narrow behavior.

## 6. Acceptance criteria

- Modelserver classifies with no torch/transformers; artifact SHA-256 verified at boot; model card present. *(WS4)*
- Model card includes the mandatory three-model comparison: classical ML, DL/ONNX, and LLM zero-shot baseline. *(WS4)*
- Classifier input carries no `tenant_id`; below-threshold predictions abstain to `other_agent`. *(WS4)*
- Guardrails enforce platform rails always-on; tenant rails cannot weaken a platform DENY. *(WS5)*
- Redaction runs before any log/trace/memory/error output; a fake-API-key test proves no raw secret leaks. *(WS2 ✅; extended in WS6)*
- Redaction hardening covers the required detector set and leak surfaces, including access logs and generated CI artifacts. *(WS7)*
- `API→modelserver` and `API→guardrails` require a verified service token and fail closed without it. *(WS1 ✅)*
- Every request is traceable via `request_id` / `X-Request-ID` end-to-end. *(WS2 ✅)*
- Red-team CI gate passes at the required rates and goes red on any safety regression. *(WS6)*
- Target endpoint names are reachable as additive aliases with old names retained. *(WS3)*

## 7. Test strategy

- **Per-service unit tests** (`uv run python -m pytest -q` in `modelserver`, `guardrails`, `backend`): auth (done), redaction + request-id (done), classify/threshold/hash-fail-closed (WS4), rails precedence (WS5), alias parity (WS3).
- **Eval gates** as `evals/<gate>/run.py` per the `001` CI-gate contract: `classifier` (macro-F1 ≥ threshold), `redteam_cross_tenant` (= 1.00), `redaction` (= 1.00); each prints `GATE=… STATUS=… OBSERVED=… THRESHOLD=…`, exits 0/1/2, and writes root `artifacts/` output only when `--output` is explicitly passed.
- **Canonical thresholds source:** Owner C gates read the root [`eval_thresholds.yaml`](../../eval_thresholds.yaml). The older [`evals/eval_thresholds.yaml`](../../evals/eval_thresholds.yaml) is legacy RAG/router data and is not canonical for Owner C gates.
- **Red-team fixtures** for the seven categories in `evals/redteam_cross_tenant/fixtures/`.
- **No-heavy-dep CI assertion**: serving lockfiles contain no `torch`/`transformers`.

## 8. Out of scope (this feature)

- Endpoint **rename/removal** and forced caller migration (only additive aliases here).
- Tenant DB schema, RLS, migrations (Owner A).
- Agent wiring and tool implementations (Owner B).
- Editing `.github/workflows/ci.yml` and admin UI (Owner D).
- Editing non-Owner-C root specs.
