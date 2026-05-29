# Contract — Guardrails API

**Owner**: Dina — Owner C: Models, Security & Guardrails.

Wire contract for the guardrails sidecar. Normative rationale (platform vs tenant rails, redaction, precedence) lives in [`models_security_guardrails_SPEC.md`](../../models_security_guardrails_SPEC.md) §6–§7; this file pins only the concrete shape. Base URL: `settings.guardrails_url` (default `http://guardrails:8010`). Platform floor: `guardrails/app/platform_floor.yaml`; enforcement: `backend/app/services/guardrail_floor.py`.

## Auth & headers (WS1/WS2 — implemented)

| Header | Required | Notes |
|--------|----------|-------|
| `Authorization: Bearer <service credential>` | Yes (all except `/health`) | `hmac.compare_digest`; missing/wrong/unset ⇒ **401**. Internal **service** identity only — **not** tenant identity. |
| `X-Request-ID` | Propagated | Attached by the backend inference client; generated at the edge if absent. |

`tenant_id`, **if present**, is a server-injected trusted field only — **never** accepted from the visitor body, query params, frontend, or model/LLM output.

## `GET /health` — public
`{ "status": "ok", "service": "guardrails", "app": "albert" }`.

## `POST /check-input` & `POST /check-output` — current (auth-protected)
Placeholders today: ignore the body and return `{"allowed": true, "reason": "phase_1_placeholder"}`. Auth is enforced. **Retained** after the aliases land (no rename).

## `POST /guardrails/input` & `POST /guardrails/output` — target aliases (WS3, additive)
Added alongside the current paths (same handlers); old paths **kept**, not renamed.

- **input** — inspect inbound conversation text before the model/agent: detect/block prompt injection, jailbreak, cross-tenant extraction, system-prompt extraction.
- **output** — inspect model/agent output before it returns or is persisted: redact PII/secrets; block system-prompt leakage and cross-tenant content.

**Request** (WS5)
```json
{ "text": "string (required, non-empty, bounded length)",
  "context": {
    "source": "input | output",
    "request_id": "optional server-issued correlation id",
    "tenant_id": "optional server-injected verified tenant id only",
    "tenant_rails": {
      "allowed_topics": [],
      "blocked_topics": [],
      "enabled_tools": [],
      "tone": "optional tenant-admin configured value"
    }
  } }
```

- Visitor/client/model input MUST NOT be trusted for `tenant_id`.
- If `tenant_id` is present, it must come from verified backend context only.
- Raw secrets and raw PII MUST NOT be copied into logs or trace attributes.
- Tenant rails are optional and may only narrow behavior.

**Response** (WS5)
```json
{ "allowed": true,
  "action": "allow | block | redact",
  "categories": [],
  "redacted_text": null,
  "reason": "" }
```

Response semantics:

- `allowed=true`, `action=allow`: no platform/tenant rail blocked the text.
- `allowed=true`, `action=redact`: text is allowed only after redaction;
  `redacted_text` contains safe text and raw values are never returned in logs/traces.
- `allowed=false`, `action=block`: text must not continue to the next stage.
- `categories` contains stable machine-readable category names such as
  `prompt_injection`, `jailbreak`, `cross_tenant`, `system_prompt_extraction`,
  `tenant_id_override`, `tool_abuse`, `pii`, `secret`, `credit_card`.
- `reason` is safe for logs and operators; it must not contain raw user text,
  secrets, Authorization headers, cookies, prompts, or raw PII.

## Rails precedence (WS5 — hard rule)
- **Platform rails** (prompt injection, jailbreak, cross-tenant refusal, system-prompt-leak, PII/secret redaction): always-on, **not tenant-editable**.
- **Tenant rails** (allowed/blocked topics, persona/tone, enabled tools): `tenant_admin`-only, own tenant.
- A platform **DENY** always overrides a tenant **ALLOW**; tenant rails may only **narrow** behavior — enforced via `guardrail_floor.enforce_floor()`.

## Constraints
- Serving image: FastAPI + uvicorn + **NeMo Guardrails** (tenant topical rails) behind a
  deterministic platform-deny prefilter — still **no torch/transformers**. NeMo runs with
  no LLM and no embeddings (custom-action topic policy). See ADR-010. NeMo is isolated to
  this sidecar; backend/modelserver stay lean.
- Fail closed on auth; redaction fails closed (redact rather than pass).
