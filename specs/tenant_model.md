# Tenant Model — Specification

**Status**: Draft · **Scope**: data model + isolation rules only (no code, no migrations)

## Purpose

Tenant isolation is the core security boundary in Albert. Albert is multi-tenant: many
businesses share one deployment. Tenant A must never be able to read or write Tenant B's data
(content, vectors, conversations, messages, leads, widget config, guardrail config, costs, or
sessions). This document defines the tenant entity, the `tenant_id` convention, which tables are
platform-owned vs tenant-owned, and the Row-Level Security (RLS) + session-variable pattern that
enforces isolation at the database layer. It is the contract that all later tenant DB code must
satisfy.

## Tenant entity

A **tenant** represents a single business customer of Albert. It is the unit of isolation: every
piece of tenant-owned data belongs to exactly one tenant.

### `tenants` table (platform-owned)

| Column       | Type        | Notes |
|--------------|-------------|-------|
| `id`         | UUID        | Primary key, UUID v4, server-generated. This is the canonical `tenant_id`. |
| `name`       | text        | Human-readable business name. |
| `slug`       | text        | URL-safe identifier derived from `name` (see below). Unique. |
| `status`     | text        | Lifecycle state, e.g. `active`, `suspended`, `erased`. |
| `created_at` | timestamptz | Set on insert. |
| `updated_at` | timestamptz | Updated on change. |

### `slug`

- A URL-safe, human-readable identifier generated from the tenant `name`
  (e.g. "Acme Co." → `acme-co`).
- Used for **display** and **admin/console URLs** only.
- **Not** used for authorization or tenant resolution. Authorization always uses the verified
  `tenant_id` (UUID), never the slug. A guessable/typed slug must never grant access.

## `tenant_id` convention (NON-NEGOTIABLE)

- **Column name**: `tenant_id` on every tenant-owned table.
- **Type**: `UUID`, specifically **UUID v4**.
- **Server-generated**: created by the platform when a tenant is provisioned. Clients never
  choose it.
- **Source of truth at request time**: `tenant_id` is derived **only** from verified context —
  the authenticated session / auth token / signed widget token. It is resolved server-side after
  verifying that token.
- `tenant_id` **MUST NEVER** come from:
  - the request body,
  - query parameters,
  - any frontend-supplied value,
  - the LLM / model output.
- Any code path that reads `tenant_id` from an untrusted source is a critical defect.

## Platform-owned tables

These are owned by the platform, not scoped to a single tenant by RLS (they describe or span
tenants). Access is controlled by platform/admin logic, not by `app.current_tenant`.

- `tenants` — the tenant registry.
- `users` — platform user accounts.
- `tenant_memberships` — which users belong to which tenants, and with what role.
- `audit_logs` — security/audit trail across the platform.

> Note: `users`, `tenant_memberships`, and `audit_logs` reference tenants but are managed by
> platform logic. They are intentionally **not** in the tenant-owned RLS set below; their access
> rules are defined by the auth/role model (separate spec).

## Tenant-owned tables

Every table below is scoped to a single tenant and **MUST** include:

```sql
tenant_id UUID NOT NULL
```

Tenant-owned tables:

- `cms_pages`
- `content_chunks`
- `conversations`
- `messages`
- `leads`
- `widget_configs`
- `tenant_guardrail_configs`
- `cost_events`

## Row-Level Security (RLS)

Every tenant-owned table MUST have RLS enabled and forced, with a tenant-isolation policy keyed
on the per-request session variable `app.current_tenant`.

### Policy template (apply to each tenant-owned table)

```sql
ALTER TABLE <table_name> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table_name> FORCE ROW LEVEL SECURITY;

CREATE POLICY <table_name>_tenant_isolation
ON <table_name>
USING (
  tenant_id = current_setting('app.current_tenant', true)::uuid
)
WITH CHECK (
  tenant_id = current_setting('app.current_tenant', true)::uuid
);
```

- `FORCE ROW LEVEL SECURITY` ensures the policy applies even to the table owner.
- `USING` guards reads/updates/deletes; `WITH CHECK` guards inserts/updates so a row can never be
  written with a different tenant's id.
- `current_setting('app.current_tenant', true)` uses the missing-ok form (`true`) so an unset
  variable yields `NULL` rather than an error — and `NULL = tenant_id` matches **no rows** (fail
  closed), rather than leaking data.

## Per-request session variable pattern

The application sets the tenant context for the duration of each request/transaction using
`set_config` with `is_local = true` (transaction-scoped, i.e. equivalent to `SET LOCAL`):

```sql
SELECT set_config('app.current_tenant', :tenant_id, true);
```

- `:tenant_id` is the verified UUID resolved from the auth/session/widget token (never from
  client input).
- `is_local = true` scopes the setting to the current transaction, so it does not bleed across
  requests within the same physical connection.

### Reset-on-exit (finally block)

The application MUST reset `app.current_tenant` at the end of every request, in a `finally`
block, so the value never survives into a later request on the same connection:

```text
try:
    set app.current_tenant = <verified tenant_id>   # SET LOCAL via set_config(..., true)
    ... handle request / run queries ...
finally:
    reset app.current_tenant                          # e.g. RESET or set_config(..., '', true)
```

### The pooled-connection bug this prevents

Connections are reused from a pool. If a connection used by **Tenant B** is returned to the pool
**without resetting** `app.current_tenant`, it carries stale tenant context. A later request for
**Tenant A** that reuses that connection could then run under Tenant B's context (or vice versa),
reading or writing the wrong tenant's rows. Transaction-local `SET LOCAL` plus a `finally` reset
closes this hole: context is bound to the transaction and explicitly cleared on exit, so a pooled
connection never hands one tenant another tenant's context.

## Repository-layer filtering (defense-in-depth)

RLS is the primary enforcement, but it is **not** the only line of defense. The repository layer
MUST still filter every tenant-scoped query by `tenant_id` explicitly. This protects against:

- a missing/disabled RLS policy on a new table,
- an unset or wrong session variable,
- queries run on a connection/role that bypasses RLS.

Belt-and-suspenders: both RLS and explicit repository filtering must hold.

## pgvector / `content_chunks`

`content_chunks` stores embeddings for RAG and is tenant-owned. Vector similarity search MUST be
tenant-filtered:

- `content_chunks` includes `tenant_id UUID NOT NULL` and is covered by the RLS policy above.
- Every retrieval/ANN query MUST be constrained to the current tenant (via RLS **and** an explicit
  `tenant_id` predicate in the repository). A nearest-neighbor search must never return another
  tenant's chunks.

## Tenant Manager boundary (not god mode)

The Tenant Manager (platform operator role) has **lifecycle** power, not **content** power.

- **Can**: provision a tenant, suspend a tenant, erase a tenant, and read **aggregate** usage
  (e.g. counts, costs in aggregate).
- **Cannot**: read tenant conversations, messages, leads, or CMS content; cannot read any private
  tenant data. Lifecycle and aggregate access never imply row-level read access to tenant content.

## Acceptance criteria

- Every tenant-owned table listed above has a `tenant_id UUID NOT NULL` column.
- Every tenant-owned table has RLS **enabled and forced** with the isolation policy template.
- `tenant_id` at request time is always derived from verified auth/session/widget context; no code
  path reads it from body, query params, frontend, or LLM output.
- Each request sets `app.current_tenant` via `set_config(..., true)` and resets it in a `finally`
  block; no connection returns to the pool with stale tenant context.
- An unset `app.current_tenant` matches **no rows** (fail closed), never all rows.
- Repository-layer queries for tenant-owned tables include an explicit `tenant_id` filter in
  addition to RLS.
- `content_chunks` vector search returns only the current tenant's chunks.
- The Tenant Manager can provision/suspend/erase and read aggregate usage, but cannot read tenant
  conversations, leads, messages, or CMS content.
- `slug` is never used for authorization.

## Out of scope

- Database migrations and DDL execution.
- ORM models / repository implementations.
- Authentication, session handling, and the role/permission model (separate role-model spec).
- Widget token issuance/verification details.
- Tenant provisioning workflow and erasure mechanics (beyond the boundary defined here).
- Performance tuning / indexing strategy for pgvector.
