# Agent Tool Contracts — Specification

**Status**: Draft · **Scope**: tool contracts only (no tool code, no routes, no DB)

## Purpose

Define the exactly three tools the Albert agent may call, and the safety contract every call must
satisfy. These contracts exist to preserve tenant isolation (see
[tenant_model.md](./tenant_model.md)) while the agent reasons over untrusted conversation input.

## Cross-cutting rules (apply to all tools)

- **The LLM never supplies `tenant_id`.** Any `tenant_id` appearing in model output is ignored.
- **The backend injects `tenant_id`** from verified auth/session/widget context at call time. The
  tool signature exposed to the model does **not** include `tenant_id`.
- **No tool may access another tenant.** Every read and write is scoped to the injected tenant.
- **All tool calls must be traceable**: each call records (at minimum) tool name, tenant_id,
  conversation/session id, timestamp, and outcome — without logging secrets or raw sensitive data.
- Inputs come from an untrusted LLM, so every tool **validates its inputs** before acting and
  **fails closed** (deny / no side effect) on invalid input.

---

## 1. `rag_search`

- **Purpose**: Retrieve relevant tenant CMS content chunks to ground the agent's answer.
- **Input shape**:
  - `query: string` (required, non-empty) — the search text.
  - `top_k: int` (optional, default small, e.g. 5; bounded to a max).
  - (`tenant_id` is **not** part of the model-facing input; backend injects it.)
- **Output shape**:
  - `chunks: array` of `{ chunk_id, text, source_ref, score }`. May be empty.
- **Side effect**: **None** (read-only).
- **Tenant safety rule**: Reads **only** tenant-scoped CMS chunks (`content_chunks`) for the
  injected tenant. Vector/ANN search is filtered by `tenant_id` (RLS + explicit repository
  filter). Never returns another tenant's chunks.
- **Validation requirements**: `query` must be a non-empty string within a max length; `top_k`
  coerced into `[1, max]`.
- **Failure behavior**: On invalid input or retrieval error, return an empty `chunks` result (or a
  typed error) — never fall back to unscoped or cross-tenant search.

---

## 2. `capture_lead`

- **Purpose**: Capture a sales/contact lead surfaced during the conversation.
- **Input shape**:
  - `name: string` (required).
  - `contact: string` (required) — email or phone.
  - `intent: string` (required) — short description of what the lead wants.
  - (`tenant_id` injected by backend, not model-supplied.)
- **Output shape**:
  - `{ lead_id, status }` where `status` is e.g. `captured`.
- **Side effect**: **Write** — creates a lead record for the injected tenant only.
- **Tenant safety rule**: Writes **only** to the token tenant (`leads.tenant_id` = injected
  tenant). A lead can never be written to or read from another tenant.
- **Validation requirements**: Schema-validate `name`, `contact`, and `intent` (presence, type,
  length; `contact` matches an email/phone format). Reject on failure. **Rate-limiting is required
  later** (out of scope for this contract, but the contract must remain compatible with it).
- **Failure behavior**: On validation failure, do **not** write; return a typed validation error.
  On storage error, return a failure status without partial/cross-tenant writes.

---

## 3. `escalate`

- **Purpose**: Hand the conversation off to a human (create or flag a support ticket / handoff).
- **Input shape**:
  - `reason: string` (required) — why escalation is needed.
  - `summary: string` (optional) — short context for the human.
  - (`tenant_id` and conversation id injected by backend.)
- **Output shape**:
  - `{ ticket_id, status }` where `status` is e.g. `escalated` / `flagged`.
- **Side effect**: **Write** — creates or flags a tenant-scoped human handoff/ticket.
- **Tenant safety rule**: The handoff/ticket is scoped to the injected tenant and its
  conversation. Never escalates into another tenant's queue or exposes cross-tenant context.
- **Validation requirements**: `reason` must be a non-empty string within a max length; `summary`
  bounded if present.
- **Failure behavior**: On invalid input or storage error, return a typed failure; do not create a
  cross-tenant or orphaned ticket.

---

## Acceptance criteria

- Exactly three tools are defined: `rag_search`, `capture_lead`, `escalate`.
- No tool's model-facing input includes `tenant_id`; the backend injects it from verified context.
- `rag_search` is read-only and returns only the current tenant's CMS chunks.
- `capture_lead` writes only to the token tenant and schema-validates `name`, `contact`, `intent`.
- `escalate` creates/flags only a tenant-scoped handoff/ticket.
- Every tool call is traceable (tool, tenant, conversation, timestamp, outcome) without logging
  secrets.
- Every tool validates untrusted input and fails closed; no tool can access another tenant.

## Out of scope

- Tool implementations, function signatures in code, and agent wiring.
- API routes, middleware, and authorization.
- Database models, schemas, and migrations.
- Rate-limiting implementation for `capture_lead` (required later; not specified here).
- Ticketing/CRM integrations and human-handoff routing details.
- Embedding/retrieval algorithm and pgvector indexing details.
