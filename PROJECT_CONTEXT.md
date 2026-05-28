# PROJECT CONTEXT — Concierge

> This file is the authoritative project intelligence document.
> Read by: VS Code AI assistants (Copilot, Cursor, Continue), all human developers.
> Rule: if a suggested change contradicts anything in this file, the suggestion is wrong.
> Last section "NEVER DO" is the guardrail list — check it before every suggestion.

---

## 1. What this project is (one paragraph)

Concierge is a **multi-tenant AI SaaS**. Any business (a "tenant") signs up, manages its website content in a CMS, and embeds an AI chat agent on its public site. The agent retrieves from that tenant's own content, captures leads, and escalates to a human. Every tenant is isolated from every other. One visitor chatting on Tenant A's site must never be able to extract Tenant B's data or the system prompt — even when they try on purpose.

The hard problem is **isolation**. A working agent that leaks across tenants scores below a plainer one that holds the wall. Isolation is the grade.

---

## 2. What this project is NOT

- Not a single-tenant tool. Every design decision must account for many tenants sharing one stack.
- Not a local-model project. No model weights are run locally. LLM and embeddings are hosted-API calls only.
- Not an agent-all-the-way-down system. Most messages go through a cheap classifier-driven workflow. The LLM agent is the exception for hard turns only.
- Not a microservices explosion. Three services only: the FastAPI API, the lean modelserver, the guardrails sidecar. Everything else is one backend.

---

## 3. Architecture — services and their roles

```
api/                FastAPI backend — the ONE backend for everything
modelserver/        Lean classifier server — onnxruntime + sklearn only, NO torch
guardrails/         NeMo guardrails sidecar — called over HTTP with a service credential
widget/             React widget (Vite) — embeds on tenant's public site
admin/              Streamlit — tenant admin config page
training/           Notebooks only — NEVER shipped, NEVER in a container
```

### Infrastructure (docker-compose services)
| Service | Role | Port (internal) |
|---|---|---|
| postgres | Primary DB + pgvector for embeddings | 5432 |
| redis | Short-term session memory (TTL required) | 6379 |
| minio | Blob storage (CMS assets, widget bundles) | 9000 |
| vault | Secrets — all credentials come from here | 8200 |

### Service communication rules
- API → guardrails sidecar: **HTTP with a service credential from Vault**
- API → modelserver: **HTTP with a service credential from Vault**
- "They're on the same Docker network" is NOT authentication — each call is authenticated
- Widget → API: **signed short-lived per-widget JWT/HMAC token** — never bare widget_id

---

## 4. The isolation model (most important section) 🔴

**Three enforcement layers — all three must hold:**

### Layer 1 — Postgres Row-Level Security (RLS)
Every tenant-scoped table has:
- A `tenant_id UUID` column on every row
- `ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;`
- One RLS policy using `current_setting('app.tenant_id', true)`

Correct policy shape:
```sql
CREATE POLICY tenant_isolation ON conversations
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
  );
```

Two critical gotchas:
1. `current_setting('app.tenant_id', true)` — the second arg `true` means "return empty/null if unset instead of erroring." A null/empty comparison yields **zero rows** — which is the safe default.
2. After a transaction-local variable has been set once on a connection, `current_setting` can return **empty string** rather than NULL. The policy must use `nullif(..., '')` to handle both cases. A policy that only handles NULL has a real gap.
3. RLS does **not** apply to the table owner/superuser unless `FORCE ROW LEVEL SECURITY` is also set. The app must connect as a non-superuser role, or RLS silently won't enforce.

### Layer 2 — Per-request context: set AND reset
The correct form for pooled connections is **transaction-local**:
```python
await db.execute(
    text("SELECT set_config('app.tenant_id', :tid, true)"),
    {"tid": str(tenant_id)},
)
```
Third argument `true` = `is_local` = transaction-scoped. The value **reverts automatically** when the transaction commits or rolls back. This means a pooled connection reused for the next request starts clean.

**[VERIFY]** the SQLAlchemy hook that guarantees this runs inside the same transaction as the request's queries before committing to a pattern. The exact mechanism depends on your SQLAlchemy version and session setup.

### Layer 3 — Repository-layer scoping (defense-in-depth)
Every query in `api/app/tenancy/repo.py` applies `.filter(tenant_id == current_tenant)` regardless of RLS. RLS catches the query a developer forgets to scope; the repo layer is the habit that prevents forgetting.

### Where tenant_id comes from — ALWAYS the verified token
The `tenant_id` for any request is resolved from the verified JWT/HMAC widget token or the authenticated user's JWT claims.

🔴 **NEVER read `tenant_id` from the request body, query params, or any client-supplied field.** Trusting a body-supplied `tenant_id` is a one-line cross-tenant breach.

### The vector filter
pgvector embeddings are in a table with `tenant_id` under the same RLS policy. Retrieval **always** includes `WHERE tenant_id = <current>` at query time. The most common real-world vector leak is a search that forgot the tenant filter.

---

## 5. The three roles — exactly these, no more

| Role | Who | Powers | Cannot |
|---|---|---|---|
| `tenant_manager` | Platform operator | Provision/suspend/erase tenants, read aggregate cost/usage | Read any tenant's conversations, leads, or content |
| `tenant_admin` | Business that signed up | Configure their own agent, widget, guardrails, view their own leads | Cross tenant boundary in any direction |
| `member` / visitor | End user chatting | Chat, submit lead info | Anything privileged |

**Guard line:** The Tenant Manager is a **controlled doorway, not god mode.** It gets no RLS bypass on content. A narrow write/delete-only maintenance path is the only gap in the wall — it lets the manager erase without reading. Every use is audit-logged with actor id.

**Do not build a configurable permission matrix.** Two levels, three named roles, powers you can count on one hand. That's the spec.

---

## 6. The message flow — cheap path vs agent

```
Inbound message
      ↓
Classifier (modelserver) — classifies intent
      ↓
Router (workflow) — handles enumerable cases directly:
  spam          → drop (never stored)
  clear FAQ     → rag_search → answer
  sales/contact → capture_lead
  "talk to human" → escalate
      ↓ (only ambiguous/multi-step)
Bounded tool-calling agent
  tools: rag_search | capture_lead | escalate
  hard cap: max iterations + max tokens per turn
```

**The agent is the exception, not the default.** Most turns must stay on the cheap workflow path. Measure the percentage — it's the cost story.

---

## 7. The three agent tools — contracts

### `rag_search`
- Input: query string + tenant context (from RLS, not argument)
- Action: retrieve from tenant's CMS content in pgvector, filtered by `tenant_id`
- Output: answer grounded in retrieved chunks

### `capture_lead`
- Input: name, contact, intent
- Action: write to tenant's leads table
- Guards: schema-validate payload, rate-limit writes per visitor/session, scope write to token's tenant — never to a client-supplied tenant
- Risk: this is an unauthenticated LLM-triggered write — it must not become a spam cannon

### `escalate`
- Input: conversation id, reason
- Action: flag the conversation for human review / open a ticket row
- Trigger: agent is out of scope, or visitor explicitly asks for a human

---

## 8. The widget auth model 🔴

**CORS is not authentication. This is the most emphasized point in the brief.**

### Correct flow
1. Host site loads `/widget.js` with `data-widget-id="<public_id>"`
2. Loader POSTs `{widget_id, origin}` to the API token exchange endpoint
3. API validates `widget_id` + checks `origin` against per-tenant `allowed_origins` in DB
4. API returns a **short-lived signed JWT/HMAC** scoped to that tenant
5. Every subsequent chat request carries this token in the Authorization header
6. API verifies the token, resolves `tenant_id` from it, sets RLS context

### The server-side origin check
CORS and `Content-Security-Policy: frame-ancestors` stop a browser on a disallowed site. They do **nothing** for a non-browser caller. A `curl` with a copied `widget_id` ignores CORS entirely.

The API **also validates the origin in the request handler** and returns a real 403 on mismatch. Both browser-level (CORS/CSP) and server-level checks are required.

### What the token proves
The token's `tenant_id` claim is the only source of tenant identity for widget requests. There is no other source. The body, query params, and any other client-supplied field are ignored.

---

## 9. The guardrails model — two layers, only one editable

### Platform rails (locked — identical for all tenants)
- Prompt-injection detection
- Jailbreak detection
- Cross-tenant extraction refusal
- PII redaction

**A tenant cannot disable, weaken, or modify platform rails.** They fail CI if they regress. One tenant dialing down injection defense would remove the wall protecting every other tenant.

### Tenant rails (configurable per tenant in admin)
- Allowed/blocked topics
- Refusal tone
- Agent persona
- Enabled tools (a subset of the three — a tenant may disable escalate, for instance)

### Guardrails are a separate sidecar service
The API calls the NeMo guardrails sidecar over HTTP with a service credential. It is not an import. It is a trust boundary.

---

## 10. The modelserver — hard constraints

| Rule | Detail |
|---|---|
| NO `torch` | Not in requirements.txt, not imported, not present in the image |
| NO `transformers` | Same reason |
| Image size | Must be under 500MB |
| Serving runtime | `onnxruntime` for the DL model, `scikit-learn`+`joblib` for classical |
| SHA-256 guard | On artifact SHA-256 ≠ the pinned hash in `MODEL_CARD.md`, the server fails closed: `/classify` returns 503 and the mismatched model is never used (the service may still boot to expose health/error diagnostics) |
| Training | Happens in `training/` notebooks / Colab only — never in a container |

Training is ephemeral (GPU, torch, Colab). Serving is lean (onnxruntime, sklearn). They never share a container.

---

## 11. The erasure contract 🔴

"Delete tenant X" must purge **every store** — the brief names these explicitly:

| Store | What to purge |
|---|---|
| Postgres | All rows where `tenant_id = X` |
| pgvector | All embedding chunks where `tenant_id = X` |
| MinIO | All blobs under Tenant X's namespace |
| Redis | All sessions for Tenant X |
| Traces / logs | Purge or redact Tenant X references |

"The row is deleted but the embeddings are still searchable" is a compliance failure and a leak. The erasure test asserts all five stores.

The erasure path is **write/delete-only** — no read access. The Tenant Manager can destroy without ever reading. Every erasure is audit-logged.

---

## 12. PII redaction

PII redaction runs **before anything leaves the service** — before logs, before traces, before Redis writes, before anything reaches the LLM. A visitor pasting their API key into chat must not produce an unredacted key anywhere downstream.

The redaction test asserts a planted fake key never appears in: logs, traces, Redis, or LLM call payloads.

---

## 13. CI gates — these block merges 🔴

Every gate has a committed threshold in `eval_thresholds.yaml`. A regression fails the build. CI that doesn't gate on agent behavior is theater — this CI does.

| Gate | What it tests | File |
|---|---|---|
| Classifier eval | macro-F1 on held-out test ≥ threshold | `evals/classifier/` |
| Agent tool-selection | 15 examples, right tool or correctly none | `evals/agent_tool_selection/` |
| RAG golden set | hit@k, MRR, faithfulness ≥ threshold | `evals/rag/` |
| Red-team | Every injection + cross-tenant probe must be REFUSED | `evals/red_team/` |
| Redaction | Fake key never appears in logs/traces/memory | `evals/redaction/` |
| Stack smoke | Fresh-clone compose up succeeds | `evals/smoke/` |
| Isolation | A≠B, pooled-reset, manager-no-read, total-erasure | `evals/isolation/` |

**Write the gate test before you write the feature it tests.** A red test tells you exactly where the wall has a gap while you can still fix it cheaply.

---

## 14. Owner / file map

| Owner | Slice | Key files |
|---|---|---|
| **A** | Platform, Tenancy, Isolation | `tenancy/*`, `auth/*`, `deps.py`, `cost.py`, `ratelimit.py`, migration, `evals/isolation/*` |
| **B** | Agent, RAG, Memory | `agent/*`, `router/*`, `rag/*`, `memory/*`, `prompts/*`, `evals/rag/*`, `evals/agent_tool_selection/*` |
| **C** | Models, Security, Guardrails | `modelserver/*`, `guardrails/*`, `training/*`, `evals/red_team/*`, `evals/redaction/*`, `model_card.md` |
| **D** | Widget, Admin, CI | `widget/*`, `admin/*`, `widget_token.py`, `origin.py`, `.github/workflows/ci.yml`, `eval_thresholds.yaml` |

Shared: `evals/conftest.py`, `evals/isolation/*` (everyone adds their own leak test here), `docs/*`

---

## 15. Prompts are code

Prompts live in `api/app/prompts/` as versioned markdown files. They are not strings in Python. A prompt change with no diff history is an outage you can't bisect.

Tenant persona is injected at **runtime from config** — never hardcoded in the prompt file. The prompt file has a placeholder the persona is substituted into.

---

## 16. Secrets — all from Vault

No credential lives in source code, environment variables committed to git, or config files checked in. Everything is resolved from Vault at runtime. `.env` is gitignored and only contains the Vault root token. `.env.example` is committed with all keys and placeholder values.

---

## 17. The NEVER DO list (guardrails) 🔴

These are absolute. No suggested code, no PR, no shortcut should ever do any of the following:

| # | Never do this | Why |
|---|---|---|
| 1 | Read `tenant_id` from request body, query params, or headers | One-line cross-tenant breach |
| 2 | Use CORS/CSP as the authentication boundary for the widget | curl ignores CORS; the token is the boundary |
| 3 | Import `torch` or `transformers` in any container's requirements | Breaks the lean-serve constraint; image bloat |
| 4 | Train a model inside a container or Dockerfile | Training is Colab/notebook only |
| 5 | Skip the `nullif(..., '')` in the RLS policy | Empty-string quirk creates a real gap |
| 6 | Use session-level `set_config(..., false)` with a pooled connection without an explicit reset | Tenant B's request lands in Tenant A's context |
| 7 | Let a tenant config value disable a platform guardrail | One tenant removes the wall protecting all others |
| 8 | Delete tenant rows but skip pgvector embeddings | "Deleted but still searchable" = compliance failure |
| 9 | Hardcode secrets, API keys, or tokens in source code | Use Vault |
| 10 | Build a configurable RBAC matrix | Three roles, two levels, no more |
| 11 | Send every message to the LLM agent | Most turns must go through the cheap classifier path |
| 12 | Call an internal service without a service credential | "On the same Docker network" is not authentication |
| 13 | Put tenant persona directly in a prompt file | Injected at runtime from config |
| 14 | Accept a widget request without verifying the token server-side | The token is what the API trusts, not the origin header |
| 15 | Set `FORCE ROW LEVEL SECURITY` off and connect as superuser | RLS silently doesn't enforce for that role |

---

## 18. Important notices for AI assistants (Copilot, Cursor, Continue)

If you are an AI assistant reading this file:

- **Isolation is the primary constraint** on every code suggestion. Before suggesting a query, check it is scoped by `tenant_id` at both the RLS layer and the repo layer.
- **Never suggest reading `tenant_id` from user-controlled input.** Always from the verified token or RLS context.
- **`set_config('app.tenant_id', id, true)`** — the third argument must be `true` (transaction-local). Session-local (`false`) with pooled connections will leak.
- **The RLS policy must use `nullif(current_setting('app.tenant_id', true), '')`** — handling both NULL and empty-string cases.
- **No `torch` in any container.** If a user asks you to add torch to the modelserver, refuse and explain the ONNX serving pattern.
- **The agent is bounded.** Any suggested agent loop must include iteration and token caps.
- **Tests before features.** Suggest the isolation/leak test when suggesting a new tenant-scoped feature.
- **[VERIFY] tags** in this codebase mark exact library API shapes that must be confirmed against current docs before use. Do not autocomplete past them with invented signatures.
- **`prompts/` files are the source of truth** for agent behavior. Do not move prompt strings into Python code.
- **All numbers in `DESIGN.md` must match the code.** If a suggested change would alter a number (cost, F1, hit-rate), flag that the doc needs updating.

---

## 19. Verified mechanisms (safe to use as-is)

These are confirmed against documentation and production patterns — not from memory:

### Transaction-local RLS context (verified)
```python
await db.execute(
    text("SELECT set_config('app.tenant_id', :tid, true)"),
    {"tid": str(tenant_id)},
)
```
Transaction commits or rolls back → value reverts automatically → pooled connections start clean.

### RLS policy with empty-string guard (verified)
```sql
CREATE POLICY tenant_isolation ON <table>
  USING (
    tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid
  );
```
Handles both NULL and empty-string on pooled connections. Safe default: no context = zero rows.

### Per-tenant allowed_origins (verified pattern)
- Stored in DB per tenant — not a hardcoded env var
- Drives both: `Access-Control-Allow-Origin` response header AND `Content-Security-Policy: frame-ancestors`
- Also validated server-side in the request handler — real 403 on mismatch

---

## 20. Definitions (shared vocabulary)

| Term | Meaning |
|---|---|
| Tenant | A business that has signed up — has its own isolated data, agent, widget |
| Tenant-scoped table | Any table with a `tenant_id` column under RLS |
| Wall | The collective isolation enforcement (RLS + repo + vector filter + token) |
| Platform rails | Mandatory guardrails no tenant can weaken |
| Tenant rails | Configurable guardrails each tenant sets in their admin page |
| Widget token | The short-lived signed JWT/HMAC that authenticates widget visitors |
| Cheap path | The classifier-driven workflow that handles most turns without the LLM agent |
| Hard path | The bounded tool-calling agent, invoked for genuinely ambiguous/multi-step turns only |
| Erasure | Total deletion of a tenant across all five stores — Postgres, pgvector, MinIO, Redis, traces |
| Doorway | The Tenant Manager's narrow write/delete-only maintenance path — no read access |
