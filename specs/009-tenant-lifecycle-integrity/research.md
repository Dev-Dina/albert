# Phase 0 Research: Tenant Lifecycle Integrity

All NEEDS CLARIFICATION were resolved during `/speckit-clarify`. Remaining decisions are
implementation choices, recorded below in Decision / Rationale / Alternatives form.

## D1 — Erasure delete ordering so escalation counts are accurate

**Decision**: Insert `escalations` into `_TENANT_TABLES` **before** `conversations`
(immediately after `messages`). Keep `tenant_memberships` placement free (no FK ordering
constraint applies).

**Rationale**: `escalations.conversation_id` has `ON DELETE CASCADE` to `conversations`.
If `conversations` is deleted first, the database cascade empties `escalations`, so a
later `DELETE FROM escalations ... RETURNING id` would return **zero** rows and the audit
summary would undercount (FR-004 violation: "report a per-category deleted-row count").
Deleting `escalations` first makes the explicit delete land on real rows and produces an
accurate count, and the data is destroyed explicitly rather than incidentally (FR-002).
`escalations` also has its own `tenant_id` FK to `tenants` (`ON DELETE CASCADE`) which
never fires because erasure marks the tenant `erased` instead of deleting it — confirming
explicit deletion is required.

**Alternatives considered**:
- *Rely on the existing cascade and just add a summary line of 0*: rejected — fragile,
  inaccurate count, and breaks if the FK or erasure-tombstone behavior changes later.
- *Add a DB `ON DELETE CASCADE` from `tenants`*: rejected — requires a migration
  (protected) and still wouldn't fire given the tenant tombstone; the spec mandates
  code-only.

## D2 — Deleting `tenant_memberships` under the erasure RLS context

**Decision**: Add `tenant_memberships` to `_TENANT_TABLES`; it is deleted by the existing
`_delete_tenant_rows` helper (`DELETE FROM tenant_memberships WHERE tenant_id = :tid
RETURNING id`).

**Rationale**: Verified against the live DB — `tenant_memberships` has
`relrowsecurity = f` (no RLS), so the delete is not gated by `app.current_tenant` and
works under the production `albert_app` (NOBYPASSRLS) role exactly as for the other
tables. The table has an `id` primary key, so `RETURNING id` yields a correct count. Only
the membership *link* is deleted; `users` rows are untouched (a user may belong to other
tenants), satisfying the erasure contract "delete all rows WHERE tenant_id = X" without
over-deleting (Assumption in spec).

**Alternatives considered**:
- *Delete the membership via a `users`/`tenants` cascade*: rejected — erasure keeps a
  tenant tombstone and never deletes users, so neither cascade fires.
- *Leave memberships and rely on status enforcement*: rejected — leaves a residual
  user↔erased-tenant row, a direct contract/compliance violation (the empirically
  observed defect).

## D3 — Coverage guard: source of truth

**Decision**: Primary guard is a host-runnable test that introspects SQLAlchemy
`Base.metadata`: for every mapped table that has a `tenant_id` column, assert it is
present in the erasure coverage set (`_TENANT_TABLES ∪ _OPTIONAL_LEGACY_TABLES`). A
secondary assertion in the Postgres eval introspects `information_schema.columns` against
the live DB for the same property.

**Rationale**: The two tables missed by this feature were each added by a *later* feature
without updating erasure. A metadata-based test is deterministic, needs no database, runs
on every `uv run pytest`, and fails the build the moment a new ORM model with `tenant_id`
is added without erasure coverage — naming the offending table (User Story 3, SC-003).
The live `information_schema` check additionally catches a table created by raw SQL
migration that has no ORM model. Together they make the gap non-recurring.

**Alternatives considered**:
- *Only the live information_schema check*: rejected as the primary — it requires
  Postgres and so would not run on the default host test path, weakening the tripwire.
- *Only the metadata check*: kept as primary but supplemented, because a raw-SQL-only
  table would escape ORM metadata.

## D4 — Status enforcement placement (DRY) and login semantics

**Decision**: One new `app/tenancy/status.py` with:
- `is_tenant_active(db, tenant_id) -> bool` — reads `tenants.status` (platform table, no
  RLS) and returns `status == "active"`.
- `user_has_active_tenant(db, user_id) -> bool` — exists-query joining
  `tenant_memberships` → `tenants` for any membership whose tenant is active.

Enforcement points:
1. **`auth.py login`**: after `authenticate`, if the user is **not** a platform manager
   and `user_has_active_tenant` is false → raise the existing generic
   `_invalid_credentials` (401). Platform managers (no membership) and users with ≥1
   active tenant proceed.
2. **`roles.resolve_current_user`**: for a tenant-scoped principal, after selecting the
   membership, if `is_tenant_active(membership.tenant_id)` is false → raise 403 with the
   same shape as the existing "No role assigned." refusal. This is the single chokepoint
   behind `get_current_user` → `get_admin_tenant_id`, so all tenant-admin API paths are
   covered without touching each route.
3. **`widget_session_service.exchange`**: after resolving `lookup.tenant_id`, if
   `is_tenant_active` is false → raise `WidgetSessionError` (route turns it into the
   existing uniform 403).
4. **`deps.get_widget_session`**: after verifying token claims, before `yield`, if
   `is_tenant_active(claims tenant)` is false → raise the existing generic widget 401.

**Rationale**: Centralizing the read keeps the four checks consistent and auditable
(Principle II) and avoids four subtly-different inline queries. The login rule
("no active tenant" only) was chosen in clarification to avoid locking multi-tenant users
out of their still-active tenants and to keep platform-operator lifecycle access (FR-014).
Resolving status at `resolve_current_user` rather than per-route guarantees no admin path
is missed. All reads target `tenants` (no RLS) so they need no `app.current_tenant`
context and add only one indexed lookup.

**Alternatives considered**:
- *Add a status check to each admin route*: rejected — many call sites, easy to miss one,
  violates DRY/auditability.
- *Enforce status inside RLS policies*: rejected — requires migration/policy change
  (protected, out of scope) and cannot express the login/widget cases.
- *Block login for any non-active membership*: rejected in clarification (over-broad for
  multi-tenant users).

## D5 — No new information leak (FR-016)

**Decision**: Reuse each surface's existing generic refusal verbatim: login →
`401 Invalid credentials`; admin resolution → `403` identical in shape to "No role
assigned."; widget handshake → existing uniform `403`; chat → existing generic widget
`401`.

**Rationale**: The widget paths already collapse all failure modes to one uniform
response to prevent enumeration (feature 006/007). Matching that for status keeps
"suspended" vs "erased" vs "not found" indistinguishable, satisfying FR-016 with zero new
surface area.

**Alternatives considered**: A distinct "tenant suspended/erased" error — rejected in
clarification (discloses tenant lifecycle state, including to unauthenticated visitors).
