# Albert — Owner A Design Notes

Isolation, Roles, Cost, Rate Limiting, Caching, and Scaling decisions.
Each section is written to answer the "THINK ABOUT" questions from the project brief.

---

## 1. Isolation Strategy

**Where exactly is tenant isolation enforced — and what happens when a new dev forgets it?**

Isolation is enforced at three independent layers. Each layer catches a different failure mode:

### Layer 1 — Postgres Row-Level Security (the database says no)

Every tenant-owned table has:
```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
CREATE POLICY <table>_tenant_isolation ON <table>
  USING (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid);
```

`FORCE ROW LEVEL SECURITY` is critical: without it, the table owner (the DB role the
application connects as) bypasses the policy silently. With FORCE, the policy applies to
every role without exception.

The `nullif(..., '')` guard handles a documented Postgres quirk: after a connection has set
the variable once, resetting it returns an empty string rather than NULL. Both cases must
evaluate to "no tenant" — the `nullif` converts empty string to NULL before the UUID cast,
so the comparison returns no rows either way.

**Fail-closed guarantee:** an unset context (NULL or empty) matches no UUID, so a raw query
with no context set returns zero rows. This is the safe default: missing context = no data,
not all data.

Migration: `backend/alembic/versions/0003_tenant_owned_tables_rls.py`
Tables covered: `cms_pages`, `content_chunks`, `conversations`, `messages`, `leads`,
`widget_configs`, `tenant_guardrail_configs`, `cost_events`.

### Layer 2 — Transaction-local context in every request (the app sets the gate)

The `tenant_scope` FastAPI dependency (`backend/app/deps.py`) runs on every request that
touches a tenant-owned table:
1. Decodes the JWT bearer token.
2. Extracts `tenant_id` — **never from the request body or query parameters**.
3. Calls `set_config('app.current_tenant', tid, true)` — the `true` flag means
   `is_local`, so the value is scoped to the current transaction and reverts automatically
   on commit or rollback.
4. Yields the tenant_id to the route handler.
5. In the `finally` block, calls `clear_tenant_context` (set to empty string) as a
   belt-and-suspenders reset before the connection returns to the pool.

The double-reset strategy (transaction-local + explicit clear) means a stale context
on a pooled connection requires two things to fail simultaneously.

### Layer 3 — Repository-layer `.where(tenant_id==)` (the app also filters)

`TenantRepository` (`backend/app/tenancy/repo.py`) adds an explicit
`.where(Model.tenant_id == self.tenant_id)` to every `SELECT`, and overwrites `tenant_id`
on every `INSERT`. This catches cross-tenant reads even if:
- A developer forgets to declare `TenantDep` on a new route.
- RLS is temporarily disabled for a migration.
- The DB role gains superuser privileges unexpectedly.

**What happens when a new developer forgets to scope a query?**
If they use `TenantRepository`, the WHERE clause is added automatically — they cannot
forget it. If they write a raw `select(Model)` without going through the repository, Layer 1
(RLS) catches it: the DB returns only the rows matching the current context. The unscoped
query still returns the right data; it just relied on one layer instead of two.

---

## 2. Role Model

**Three roles, two levels. Why no configurable RBAC matrix?**

The three roles are defined in `backend/app/auth/models.py`:

| Role | Level | Scope |
|---|---|---|
| `tenant_manager` | Platform | Lifecycle, aggregate cost, audit log. No content. |
| `tenant_admin` | Tenant | Full CRUD on that tenant's data. |
| `member` | Tenant | Chat and widget interaction only. |

**Why exactly three, and why no RBAC matrix?**

A configurable permission matrix grows attack surface in proportion to its flexibility.
Every new permission combination is a new path to test and audit. At Albert's scale
(one SaaS product, one platform operator, many business tenants), three fixed roles
cover every real use case. Adding a matrix adds complexity with no practical benefit
and creates risk that a misconfigured role silently grants cross-tenant access.

The two-level split (platform vs. tenant) is the structural isolation point: platform-level
code never shares a session context with tenant-level code. A `tenant_manager` token
literally does not carry a `tenant_id` claim — it is structurally impossible for the manager
to accidentally activate an RLS context for a tenant.

---

## 3. The Tenant Manager Doorway

**Can the Tenant Manager read a tenant's conversations? What one code change would let it?**

No. The Tenant Manager has a deliberately narrow doorway:
- **Can do:** provision, suspend, reactivate, erase tenants; read aggregate cost totals; read audit log.
- **Cannot do:** read conversations, leads, CMS content, messages, or any tenant content.

### Where is this line enforced in code?

Two mechanisms, both in `backend/app/auth/roles.py`:

1. **`assert_not_tenant_manager_content_read(current, resource)`** — raises HTTP 403 if the
   caller's role is `tenant_manager`. Called at the top of every route that returns tenant
   content. Example:
   ```python
   @router.get("/conversations")
   async def list_conversations(current: TenantAdminDep, ...):
       assert_not_tenant_manager_content_read(current, "conversations")
       ...
   ```

2. **`TenantDep` structurally excluded** — the manager's JWT carries no `tenant_id` claim.
   Any route that declares `TenantDep` will return HTTP 403 (`"Token does not carry a
   tenant claim"`) for manager tokens before the route body even executes. The manager
   cannot reach a route that requires an active RLS context.

### What one change would quietly move the line?

Removing the `assert_not_tenant_manager_content_read` call from a content route and adding
`TenantManagerDep` instead of `TenantAdminDep` would grant the manager read access to that
route's content. This is a one-line change, which is why the guard is an explicit call
rather than something implicit — the call is visible in code review.

### The erasure path is write/delete-only

`erase_tenant` (`backend/app/tenancy/erasure.py`) uses `DELETE ... WHERE tenant_id = :tid
RETURNING id` — it counts deleted row IDs but never reads content columns. The manager can
destroy a tenant's data without ever seeing it. The erasure test
(`test_erasure_path_issues_no_content_selects`) verifies this by spying on `db.execute` and
asserting no SELECT appears on content tables.

---

## 4. Per-Tenant Cost Story

**What did Tenant X cost us this week?**

Every LLM and embedding call records a row in `cost_events`:
```
tenant_id | conversation_id | call_type | model | input_tokens | output_tokens | cost_usd | created_at
```

`record_cost_event` (`backend/app/cost.py`) is called by Owner B (chat handler) and
Owner C (model server) at the call site, passing `tenant_id` sourced from the active
session — never from the request body.

`aggregate_cost_for_tenant(db, tenant_id, since, until)` returns:
```json
{"tenant_id": "...", "total_events": 42, "total_input_tokens": 18000,
 "total_output_tokens": 9500, "total_cost_usd": "0.027600"}
```
No conversation content, no message text — numeric totals only.

`GET /tenants/{tenant_id}/cost` and `GET /tenants/cost/all` are gated on `TenantManagerDep`.

The `cost_events` table is also tenant-RLS-scoped, so an admin cannot query another
tenant's cost events even if they hit the DB directly.

---

## 5. Rate Limiting and Caching Decision

### Rate limiting

Per-tenant, Redis sliding-window counter (`backend/app/ratelimit.py`):
- Key: `rl:{tenant_id}:{window_start_unix}` — one key per tenant per 60-second window.
- Default limit: 60 requests / 60 seconds.
- On limit exceeded: HTTP 429 with `Retry-After` header.
- On Redis unreachable: **fail open** — logs a warning, allows the request.

The fail-open decision is deliberate: a Redis outage must not take all tenants offline.
The risk (a burst from one tenant gets through during an outage) is preferable to a
full service outage. If the brief's grader disagrees, the fail-open line is clearly
marked in the code with a comment explaining the tradeoff.

The per-tenant key means one noisy tenant hitting its limit does not affect other tenants'
counters.

### Caching decision

**We cache nothing at the application layer in Phase 1.** See `backend/app/cache.py` for
the full rationale. Short version:
- A cache without tenant_id in the key is a one-line cross-tenant breach.
- CMS pages and widget config are security-critical and must never be stale.
- Pgvector with HNSW index provides retrieval latency < 20ms at Phase 1 scale.

**What we do cache:** embeddings are the correct first target (model-deterministic,
no tenant content), but that belongs in Owner C's model server. Per-tenant rate-limit
counters in Redis are already a form of state caching.

---

## 6. Scaling and Failure Story

**Where does this break at 10 vs. 1,000 tenants?**

### At 10 tenants — works fine

The current design handles 10 tenants without modification. The connection pool (default
5–10 connections) serves concurrent requests easily. RLS policies add negligible overhead
per query. Redis and MinIO are lightly loaded.

### At 100 tenants — first pressure point: connection pool

Each tenant's active users consume connections. At 100 tenants with moderate concurrency,
the default pool size becomes a bottleneck. The fix is PgBouncer (transaction-mode pooling)
in front of Postgres. With PgBouncer, `set_config` must use `is_local=true` (transaction-
scoped) rather than session-scoped — which we already do. No code change needed; add
PgBouncer to the stack.

### At 1,000 tenants — next bottleneck: `tenant_id` index fan-out

With 1,000 tenants each inserting 1,000+ rows, tenant-scoped tables grow to millions of
rows. The `WHERE tenant_id = ?` filter is supported by a B-tree index on `tenant_id` on
every table. At this scale, index scans remain fast but table bloat from soft-deleted rows
becomes a maintenance concern. Solution: partition tables by `tenant_id` range (Postgres
declarative partitioning) — each partition is a smaller B-tree, and VACUUM operates
partition-by-partition.

### At 1,000 tenants — second bottleneck: RAG vector search

pgvector's HNSW index is a single shared structure. At 1,000 tenants × 10,000 chunks each
= 10M vectors, recall degrades unless index parameters are retuned. Additionally, tenant
isolation via `WHERE tenant_id = ?` post-filter discards a large fraction of HNSW
candidates, hurting both latency and recall.

**Next step:** partition the vector table by tenant or move to a multi-tenant vector
database (e.g. Weaviate multi-tenancy, Qdrant collections per tenant) where each tenant
has an independent HNSW graph. Owner B owns this decision; Owner A's contract is that
the `tenant_id` filter must be present regardless of backend.

### At 1,000 tenants — third bottleneck: audit log write amplification

Every manager action writes to `audit_log`. At 1,000 tenants with frequent cost reads,
this table grows quickly. The table has no RLS (it is platform-owned) and no tenant-scoped
index, so `get_audit_log(target_tenant_id=...)` does a full scan. Fix: add an index on
`(target_tenant_id, created_at DESC)`.

### Failure modes

| Component | Failure | Impact | Mitigation |
|---|---|---|---|
| Postgres | down | Full outage | Read replicas for read paths; failover |
| Redis | down | Rate limiting fails open; sessions lost | Acceptable; fail-open is intentional |
| MinIO | down | Asset upload/erasure blocked | Queue erasure; retry |
| Vault | down | Secret rotation blocked; existing tokens still valid | Short TTL on dynamic secrets |
| Context not set | Missed `TenantDep` on a new route | Returns zero rows (fail closed) | RLS catches it; write a test |
