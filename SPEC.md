# SPEC.md — Albert Multi-Tenant AI Concierge

> This file defines the tenant model, role model, and agent tool contracts.
> Full design rationale and architecture decisions live in `PROJECT_CONTEXT.md` and `docs/DESIGN.md`.

---

## 1. Tenant Model

**Unit:** A **tenant** is a single business that has signed up for the platform. Every tenant has:

| Field | Type | Notes |
|---|---|---|
| `id` | `UUID v4` | Immutable primary key — the canonical `tenant_id` throughout the system |
| `slug` | `string` | URL-safe lowercase identifier (unique) |
| `name` | `string` | Display name |
| `status` | `enum` | `active` \| `suspended` \| `erased` |

**Convention:** Every tenant-scoped table carries a `tenant_id UUID NOT NULL` column that is a foreign key to `tenants.id`. This column is never nullable and never client-supplied — it is always set from the verified auth token.

**Isolation contract:**
- `tenant_id` on any request is resolved exclusively from the verified JWT bearer token or signed widget token — never from the request body, query params, or any client-supplied field.
- Postgres Row-Level Security (`ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`) is active on every tenant-scoped table using:
  ```sql
  USING (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid)
  ```
- The app connects as a `NOSUPERUSER NOBYPASSRLS` role (`albert_app`).
- RLS context is transaction-local (`set_config(..., true)`), auto-reverts on commit/rollback.

---

## 2. Role Model

Exactly **three roles**. No configurable permission matrix.

| Role | Assigned to | Powers | Hard restrictions |
|---|---|---|---|
| `tenant_manager` | Platform operator | Provision tenants, suspend, erase, invite first admin, read aggregate cost/usage, view audit log | Cannot read any tenant's conversations, messages, leads, CMS content, or vector data — enforced by RLS (no bypass) + HTTP 403 guard |
| `tenant_admin` | Business that signed up | Configure their own agent, widget, guardrails; view their own leads and conversations; invite/remove members | Cannot cross tenant boundary in any direction |
| `member` | End user / widget visitor | Chat, submit lead info | Cannot access any privileged resource |

**Role source:** Role is read from the verified JWT payload only — never from the request body.

**Tenant Manager doorway rule:** The `tenant_manager` is a controlled maintenance path, not god mode. It has one narrow write/delete-only gap in the wall — erasure — but it cannot read through the wall. Every manager action is audit-logged with `actor_user_id`.

---

## 3. Agent Tool Contracts

The bounded tool-calling agent has exactly **three tools**. No tool may be added without updating this spec and the corresponding eval.

### `rag_search`

| Field | Value |
|---|---|
| Purpose | Retrieve grounded answers from the tenant's CMS content |
| Input | `query: string` |
| Tenant scope | Resolved from RLS context — not an argument; the tool cannot be called with a different tenant's context |
| Action | pgvector similarity search filtered by `tenant_id`; returns top-k chunks |
| Output | `answer: string`, `sources: list[chunk_id]` |
| Constraint | Must always include `WHERE tenant_id = <current>` in the vector query — the most common vector leak is a search that forgot this filter |

### `capture_lead`

| Field | Value |
|---|---|
| Purpose | Write a lead record on behalf of the visiting user |
| Input | `name: string`, `contact: string`, `intent: string` |
| Tenant scope | Write is scoped to the token's tenant — never to a client-supplied tenant |
| Action | Schema-validates payload, rate-limits writes per visitor session, inserts into `leads` table |
| Output | `lead_id: uuid` |
| Constraint | This is an unauthenticated LLM-triggered write. Rate limiting and schema validation are mandatory guards against spam cannon abuse |

### `escalate`

| Field | Value |
|---|---|
| Purpose | Flag a conversation for human review |
| Input | `conversation_id: uuid`, `reason: string` |
| Tenant scope | Scoped to the token's tenant |
| Action | Sets `escalated = true` on the conversation row; creates an escalation record |
| Output | `escalation_id: uuid` |
| Trigger | Agent is out of scope, or visitor explicitly requests a human |
| Constraint | A tenant may disable this tool in their admin config (tool availability is per-tenant configurable); platform rails cannot be disabled |

---

## 4. Erasure Contract (summary)

`DELETE /tenants/{id}` triggers a total purge across **all five stores**:

| Store | Mechanism |
|---|---|
| Postgres rows | `DELETE WHERE tenant_id = X` on 14 tenant-scoped tables |
| pgvector chunks | Covered by Postgres `CASCADE` on `content_chunks` |
| MinIO blobs | Delete all objects under `{tenant_id}/` prefix |
| Redis sessions | `SCAN` + `DELETE` on `session:{tenant_id}:*` keys |
| Traces/logs | Purge hook (Owner C implements; stubbed with runtime warning until complete) |

The erasure path is **write/delete-only** — no `SELECT` on content rows before delete. Every erasure is audit-logged with `actor_user_id`.

---

*For full isolation design rationale, scaling story, and ADRs: see `docs/DESIGN.md` and `docs/DECISIONS.md`.*
*For service architecture and NEVER DO list: see `PROJECT_CONTEXT.md`.*
