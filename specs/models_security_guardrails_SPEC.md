# Model Safety & Guardrails — Specification

**Status**: Team-aligned baseline · **Scope**: contracts only (no implementation in this doc) ·
**Area**: Model Safety & Guardrails · **Accountable owner**: Dina

> This is a team-aligned baseline. The classifier task, label set, and confidence threshold are
> accepted decisions (see §11). Nothing in this doc renames or changes existing code — endpoint
> alignment is an accepted target documented as an implementation decision, not yet applied.
> Implementation details that remain genuinely open are listed in §11.

---

## 1. Purpose

Define the contracts for Model Safety & Guardrails in Albert: the classifier API, the lean
modelserver, the guardrails sidecar (platform + tenant rails), the redaction layer,
service-to-service authentication, tracing/logging safety, and the red-team CI gate.

These contracts exist to support the project's non-negotiable goal — **tenant isolation**
(Tenant A must never reach Tenant B's data) — while the system reasons over untrusted
conversation input. This document is the contract that later implementation code must satisfy; it
does not change any code yet.

---

## 2. Existing baseline discovered

From the repo audit (actual current state):

| Area | File | Current state |
|------|------|---------------|
| Modelserver | `modelserver/app/main.py` | FastAPI. `GET /health`; `POST /predict` returns hardcoded `{"label":"unknown","confidence":0.0}`, request body ignored. |
| Modelserver deps | `modelserver/pyproject.toml`, `modelserver/Dockerfile` | Only `fastapi`,`uvicorn`. uv `--no-dev`, slim base. **No torch/transformers** — lean. ✅ |
| Guardrails | `guardrails/app/main.py` | FastAPI. `GET /health`; `POST /check-input` and `POST /check-output` return `{"allowed":true,"reason":"phase_1_placeholder"}`, body ignored. |
| Guardrails deps | `guardrails/pyproject.toml`, `guardrails/Dockerfile` | Only `fastapi`,`uvicorn`. Lean. ✅ |
| Service config | `backend/app/core/config.py` | `modelserver_url`, `guardrails_url`, `service_auth_token` (SecretStr, default `dev-service-token`) **defined but enforced nowhere**. |
| Env | `.env.example` | `MODELSERVER_URL`, `GUARDRAILS_URL`, `SERVICE_AUTH_TOKEN=dev-service-token`. |
| Vault / secrets | `backend/app/clients/vault_client.py`, `backend/app/core/secrets.py` | Async Vault KV v2 read + health; token never logged. Available for Vault-sourced service creds. |
| Logging | `backend/app/core/logging.py` | stdlib `basicConfig` only. **No request_id/trace_id, no structured logs, no redaction filter.** |
| Audit | `backend/app/db/models/audit_log.py` | `audit_logs` table (actor_user_id, target_tenant_id, action, meta JSONB). Model exists; no writer yet. |
| Eval thresholds | `eval_thresholds.yaml` | `classifier.macro_f1_min 0.60`, `redteam.required_pass_rate 1.00`, `redaction.required_pass_rate 1.00`, `smoke 1.00` (placeholders). |
| CI | `.github/workflows/ci.yml` | Placeholder — only an `echo`. No tests run, no eval gate, no red-team. ⚠️ **protected file**. |
| Test/lint harness | `Makefile` | `make test` (pytest backend/modelserver/guardrails), `make lint` (ruff). |
| Isolation auditor | `.claude/agents/tenant-isolation-auditor.md` | Read-only PASS/WARN/FAIL auditor — reusable for review/CI. |

Baseline status: modelserver and guardrails **shells exist and are lean**; everything
else (real classify/rails, redaction, service-auth enforcement, tracing, model card, red-team
CI) is **missing**.

---

## 3. Dependencies on existing specs

This spec is subordinate to and must not weaken:

- **Tenant model** — [`./tenant_model.md`](./tenant_model.md):
  `tenant_id` is the canonical boundary (UUID v4, server-generated). It comes **only** from
  verified auth/session/widget context — **never** from request body, query params, frontend,
  or LLM/model output. RLS + repo-layer filter + `app.current_tenant` per-request pattern.
- **Role model** — [`./role_model.md`](./role_model.md):
  Three fixed roles. **Tenant rails are configurable by `tenant_admin` only** (own tenant).
  `tenant_manager` is lifecycle/aggregate only — never tenant content.
- **Agent tool contracts** — [`./agent_tool_contracts.md`](./agent_tool_contracts.md):
  Three tools (`rag_search`, `capture_lead`, `escalate`). **Model-facing input never includes
  `tenant_id`**; backend injects it. Every tool validates input, fails closed, and is traceable
  without logging secrets.

These Model Safety & Guardrails contracts inherit all of the above as hard constraints.

---

## 4. Classifier contract

### Current endpoint
- `POST /predict` on modelserver (placeholder, returns `{"label":"unknown","confidence":0.0}`).

### Target endpoint (accepted, not yet applied)
- **`POST /classify`** — accepted target (see endpoint mismatch in §6 and decision O-3). The old
  `/predict` is **not** renamed by this spec; alignment happens in a later execution phase.

### Request schema
```json
{
  "text": "string (required, non-empty, max length bounded)",
  "context": { "optional": "non-sensitive routing hints only" }
}
```
- **No `tenant_id` in the model-facing input.** Classifier input is untrusted conversation text;
  it must not carry or trust a tenant identity (per tenant model + agent tool contracts).

### Response schema
```json
{
  "label": "one of the labels below",
  "confidence": 0.0,
  "model_version": "string",
  "artifact_sha256": "string"
}
```

### Labels (accepted baseline)
The label set matches Owner B's router/agent consumption:

| Label | Meaning |
|-------|---------|
| `faq_rag` | Answerable from tenant CMS content → route to `rag_search`. |
| `lead_capture` | Visitor intent to be captured as a lead → `capture_lead`. |
| `human_escalate` | Needs human handoff → `escalate`. |
| `spam` | Junk / abusive / non-genuine input → drop or low-priority path. |
| `other_agent` | None of the above / fallback agent handling. |

> These labels and their mapping to the three agent tools (`rag_search`, `capture_lead`,
> `escalate`) are the accepted baseline for visitor intent routing.

### Confidence threshold behavior (accepted baseline: start at 0.70)
- If top-label `confidence >= 0.70` → return that label.
- If `confidence < 0.70` → return **`other_agent`** (abstain to safe fallback); never guess a
  high-stakes label (`lead_capture`/`human_escalate`) below threshold.
- 0.70 is the accepted starting value; it is config-driven and reconciled with
  `eval_thresholds.yaml`, with the final value tuned against a real labeled set in the
  classifier-baseline phase.

---

## 5. Modelserver contract

- **Lean serving only.** Inference uses **sklearn/joblib and/or onnxruntime**.
- **No `torch`, no `transformers`** in the serving container (constitution + project rule).
  Any deep-learning training/export happens **offline**; only the exported artifact is served.
- **Model card required** (`modelserver/MODEL_CARD.md` in a later phase): task, dataset source +
  SHA-256, metrics, chosen deployment model, and the served **artifact SHA-256**.
- **Artifact hash check at boot**: the modelserver computes the SHA-256 of the loaded artifact
  and compares it to a pinned value. On mismatch it **refuses to serve** (fails closed); `/health`
  reports `model_version`, `artifact_sha256`, and `loaded: true|false`.
- Serving images must remain dependency-light; a CI check should assert serving lockfiles do not
  pull in `torch`/`transformers`.

---

## 6. Guardrails contract

### Current endpoints
- `POST /check-input` and `POST /check-output` (placeholders; body ignored;
  return `{"allowed":true,"reason":"phase_1_placeholder"}`).

### Target endpoints (accepted, not yet applied — see decision O-3)
- **`POST /guardrails/input`**
- **`POST /guardrails/output`**

> **Endpoint alignment (accepted target, not yet applied):**
> - Modelserver: current **`/predict`** → target **`/classify`**.
> - Guardrails: current **`/check-input`** / **`/check-output`** → target
>   **`/guardrails/input`** / **`/guardrails/output`**.
>
> Nothing is renamed yet. The alignment (with optional deprecated aliases during migration so
> callers/CI don't break) is a later execution phase. Owner B (caller) and Owner D (CI) must be in
> the loop before renaming; exact migration timing is open.

### Input guardrails (`/guardrails/input`)
- Inspect inbound user/conversation text **before** it reaches the model/agent.
- Detect & block: prompt injection, jailbreak attempts, cross-tenant extraction attempts,
  system-prompt extraction attempts.
- `tenant_id` (if present) is a **server-injected, trusted** field only — never accepted from the
  model or the visitor request body.
- Response shape:
  ```json
  { "allowed": true, "action": "allow|block|redact", "categories": [], "redacted_text": null, "reason": "" }
  ```

### Output guardrails (`/guardrails/output`)
- Inspect model/agent output **before** it returns to the user or is persisted.
- Redact PII/secrets; block system-prompt leakage and cross-tenant content.

### Platform rails vs tenant rails
- **Platform rails** (prompt injection, jailbreak, cross-tenant refusal, system-prompt-leak,
  PII/secret redaction): **always on, not tenant-editable.**
- **Tenant rails** (allowed topics, blocked topics, persona/tone, enabled tools): configurable by
  **`tenant_admin` only**, scoped to their own tenant.
- **Precedence (hard rule):** a platform **DENY** always overrides any tenant **ALLOW**. Tenant
  rails may only **narrow** behavior; they can never weaken or disable a platform rail.

---

## 7. Redaction contract

- **Redact before logs, traces, and memory.** Raw secrets and unredacted sensitive messages must
  never reach a log line, a trace span, or stored conversation memory.
- Detectors (regex-first; see decision O-6): email, phone, credit-card, API keys / tokens /
  secrets, and the agreed PII set.
- Applied on the input-logging path and on output-to-user / output-persistence.
- **Fail closed:** if a detector errors, redact rather than pass through.
- Logs record only redaction **type/count**, never the raw value.
- **Fake API key test requirement:** a test must inject a synthetic (fake) API key / secret and
  assert it is redacted everywhere it could surface (response, logs, traces, memory) and that the
  raw value never appears. Part of the `redaction.required_pass_rate = 1.00` gate.

---

## 8. Service-to-service auth contract

- **Current state:** `service_auth_token` exists in `backend/app/core/config.py` and
  `.env.example` (`SERVICE_AUTH_TOKEN`) but is **enforced nowhere**.
- **Accepted baseline:** calls **API → modelserver** and **API → guardrails** require
  `Authorization: Bearer <service credential>`.
  - The credential is sourced from **Vault** when Owner A's Vault path is ready; local dev may use
    `SERVICE_AUTH_TOKEN` from env as a fallback. No real token is committed.
  - Backend attaches the header on every internal call.
  - Modelserver and guardrails verify it and **fail closed** (HTTP 401) on missing/wrong token.
- **The internal Docker network is NOT a trust boundary.** Reachability is not authentication.
- **Not baseline (future alternatives):** OAuth2-style service JWTs and mTLS are possible future
  upgrades, not the current requirement. OAuth is **not** required by the brief and is **not**
  introduced as the baseline. See decision O-4.

---

## 9. Tracing / logging contract

- A `request_id` / `trace_id` is generated at the edge and propagated (via header) to modelserver
  and guardrails so a single request is traceable end-to-end.
- Each classify / guardrail / tool call traces, at minimum:
  - `request_id`, `tenant_id`, classifier `label` + `confidence`, guardrail `decision`, `latency`.
- **Never trace raw secrets or unredacted messages.** Redaction (§7) runs before anything is
  logged/traced. No tokens, no passwords, no raw PII, no prompt text containing PII.
- Logging is structured; a redaction filter sits on the logger. (`backend/app/core/logging.py` is
  a **protected file** — any change there must be warned/reviewed.)

---

## 10. Red-team CI contract

A red-team suite runs in CI and gates merges. Categories:

- **prompt injection** — instruction-override attempts in user input.
- **jailbreak** — attempts to bypass platform rails / role.
- **cross-tenant extraction** — attempts to read another tenant's data/content.
- **system prompt extraction** — attempts to reveal the system/platform prompt.
- **fake tenant_id override** — attempts to set/override `tenant_id` via body, params, frontend,
  or model output (must be ignored; tenant identity comes only from verified context).
- **tool abuse** — attempts to misuse `rag_search` / `capture_lead` / `escalate` (e.g. write to or
  read from another tenant, unvalidated input).
- **redaction leak** — secrets/PII surfacing in responses, logs, traces, or memory.

Gate (against `eval_thresholds.yaml`): `redteam.required_pass_rate = 1.00` and
`redaction.required_pass_rate = 1.00` — any failure makes CI red. Wiring into
`.github/workflows/ci.yml` (protected) is coordinated with Owner D.

---

## 11. Decisions

### Accepted baseline
| # | Decision | Accepted choice | Notes |
|---|----------|-----------------|-------|
| O-1 | Classifier task | Visitor intent routing | — |
| O-2 | Label set | `faq_rag, lead_capture, human_escalate, spam, other_agent` | — |
| O-8 | Confidence threshold | Start at 0.70; below ⇒ `other_agent` | Starting value; final tuned after real metrics |
| O-4 | Service auth mechanism | Vault-backed bearer service credential for baseline; local env fallback for dev; OAuth2-style JWT/mTLS are future alternatives | OAuth not required by brief; OAuth2 JWT / mTLS not adopted now |
| O-5 | Guardrails engine | Stub/rules first + tests; NeMo optional if time allows | — |
| O-6 | Redaction engine | Regex-first deterministic redaction | Presidio / Guardrails.ai not adopted now |
| O-7 | CI thresholds | Keep existing `eval_thresholds.yaml` placeholders for now | Final values set after real metrics |
| O-3 | Endpoint alignment | Target `/classify`, `/guardrails/input`, `/guardrails/output` (deprecated aliases during migration) | Accepted target — **not yet applied**; migration timing open |

### Still open (implementation details)
- Dataset choice for the classifier.
- Exact classical model choice (e.g. LogReg vs LinearSVC).
- Whether DL/ONNX ships (Phase 7 is optional).
- Final CI threshold values, set once real metrics exist.
- Exact endpoint migration timing (Phase 4).

---

## 12. Execution phases

| Phase | Goal | Notes |
|-------|------|-------|
| Phase 1 | Contract finalization | This document — team-aligned baseline. Docs only; no code, compose, or service changes. |
| Phase 2 | Service-to-service auth | Enforce Vault/env-backed bearer service credential on modelserver and guardrails; backend attaches the header; services fail closed with 401. |
| Phase 3 | Redaction + tracing safety | Regex redaction layer + `request_id`/`trace_id` propagation + structured, redacted logging. (`logging.py` protected — warn.) |
| Phase 4 | Endpoint alignment | `/predict`→`/classify`, `/check-input`/`/check-output`→`/guardrails/input`/`/guardrails/output`, with deprecated aliases during migration. Coordinate with Owner B (caller) + D (CI). Migration timing open. |
| Phase 5 | Classifier baseline + model card | Offline classical sklearn (TF-IDF + LogReg/LinearSVC); metrics vs `classifier.macro_f1_min`; `MODEL_CARD.md` + artifact SHA-256 + boot hash check. |
| Phase 6 | Guardrails + red-team tests | Real platform rails + red-team cases (§10) + CI gate against `eval_thresholds.yaml`. Coordinate with Owner D for `ci.yml`. |
| Phase 7 | Optional DL/ONNX + LLM comparison | Offline DL→ONNX export + offline LLM baseline; 3-way comparison in model card. Deferrable. |

---

## Acceptance criteria

- Modelserver serves classification with **no torch/transformers**; artifact SHA-256 verified at
  boot; model card present.
- Classifier input carries **no `tenant_id`**; below-threshold predictions abstain to a safe label.
- Guardrails enforce platform rails always-on; tenant rails cannot weaken a platform DENY.
- Redaction runs before any log/trace/memory; a fake-API-key test proves no raw secret leaks.
- API→modelserver and API→guardrails require a verified service token and fail closed without it.
- Every classify/guardrail/tool call is traceable (request_id, tenant_id, label/confidence,
  decision, latency) with no raw secrets or unredacted messages.
- Red-team CI gate passes at the required rates and goes red on any safety regression.

## Out of scope (this spec)

- Any implementation code, route handlers, or container changes.
- Renaming existing endpoints (documented as decision O-3 only).
- Tool implementations and agent wiring (Owner B).
- RLS / migrations / `app.current_tenant` plumbing (Owner A).
- Admin UI for tenant rails and widget-token issuance (Owner D).
