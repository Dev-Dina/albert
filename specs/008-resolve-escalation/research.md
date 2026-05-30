# Research: Resolve Escalation (Phase 0)

All "NEEDS CLARIFICATION" items were resolvable from the existing codebase patterns
(feature 007) and the constitution. No external research was required. Decisions below.

## D1 — `resolved_by` storage: bare nullable UUID, no DB foreign key

- **Decision**: Add `resolved_by` as a nullable `UUID` column with **no** foreign-key
  constraint to `users`. It records the acting admin's `user_id` as a light audit trail.
- **Rationale**: The brief specifies "`resolved_by uuid NULL` … for a light audit trail."
  A hard FK would couple an escalation's audit record to the user row's lifecycle (a removed
  admin user would force either CASCADE — losing the escalation — or SET NULL — losing the
  audit value). The escalations table's existing FKs (`tenant_id`, `conversation_id`) model
  *ownership*; `resolved_by` is *metadata*. Keeping it FK-free preserves the audit value
  regardless of later user changes and avoids an extra cross-table dependency in the
  RLS-forced table. The acting user is always same-tenant (derived from the verified
  membership), so there is no cross-tenant exposure risk in storing it.
- **Alternatives considered**: FK to `users(id)` with `ON DELETE SET NULL` (rejected: loses
  audit value on user removal, adds coupling); a separate `escalation_audit` table (rejected:
  out of scope — brief explicitly scopes the trail to row columns, no separate audit log).

## D2 — Two-state machine with idempotent transitions

- **Decision**: New pure module `app/services/escalation_lifecycle.py` mirroring
  `lead_lifecycle.py`. `ESCALATION_STATUSES = ("open", "resolved")`. Both directions are
  allowed (`open↔resolved`) **and** a no-op transition to the current status is allowed
  (idempotency, FR-012). Effectively: any valid status is always reachable.
- **Rationale**: FR-002 requires symmetric resolve/reopen; FR-012 requires idempotency
  (re-resolving refreshes `resolved_by`/`resolved_at`). Unlike the lead lifecycle (which is
  strict-forward and returns 409 on disallowed moves), the escalation lifecycle has **no
  disallowed transition between valid statuses** — so there is **no 409 path**. Invalid
  *values* are rejected upstream by the Pydantic enum (422). The module still exists to keep
  the rules pure/unit-testable and to mirror the established pattern.
- **Alternatives considered**: Forbid same-state transition like leads (rejected: breaks
  idempotency FR-012); inline the check in the service (rejected: less testable, diverges
  from the `*_lifecycle` pattern).

## D3 — No RLS policy change; additive migration `0016`

- **Decision**: Migration `0016_escalation_status` (down_revision `0015`) adds three columns
  to `escalations`: `status TEXT NOT NULL DEFAULT 'open'`, `resolved_at TIMESTAMPTZ NULL`,
  `resolved_by UUID NULL`. It does **not** touch the `escalations_tenant_isolation` policy or
  the `ENABLE/FORCE ROW LEVEL SECURITY` state.
- **Rationale**: RLS on `escalations` is keyed on `tenant_id` (set in 0015); adding columns
  unrelated to `tenant_id` cannot weaken or alter the policy. The `server_default 'open'`
  back-fills all existing rows to `open` so the column is immediately `NOT NULL`-safe.
- **Alternatives considered**: A Postgres `CHECK (status IN ('open','resolved'))` constraint
  (considered; **omitted** to mirror 0015/leads which validate status in the app layer, keep
  the migration parallel to the SQLite test path, and avoid a second source of truth — the
  Pydantic enum + lifecycle module are authoritative). A partial index on `status='open'`
  (rejected: escalation volume is tiny; no measurable benefit).

## D4 — Status filter location (API + UI default)

- **Decision**: `GET /api/v1/admin/escalations` gains an optional `status` query param
  (`open` | `resolved`); omitted ⇒ all. The repository filters `Escalation.status` when
  provided (always in addition to the non-negotiable `tenant_id` filter). The admin page's
  filter control **defaults to `open`** (FR-009), and offers `resolved` and `all`.
- **Rationale**: Mirrors the leads page exactly (`status_filter: str | None = Query(alias="status")`,
  UI selectbox default). The default-open requirement is a *view* default, so it lives in the
  UI control; the API stays a neutral filter. Tenant scope is always applied first regardless
  of the status filter.
- **Alternatives considered**: Hard-coding open-only in the API (rejected: prevents the
  resolved/all views FR-009 requires).

## D5 — Commit/transaction & response shape

- **Decision**: The PATCH route validates via the Pydantic enum (422 on bad value), calls
  `svc.set_escalation_status(...)`, then `await db.commit()` — mirroring the leads PATCH
  route. `EscalationResponse` is extended with `status`, `resolved_at` (nullable),
  `resolved_by` (nullable). The existing list/detail GETs return the same enriched shape.
- **Rationale**: Consistency with `admin_members_and_leads.py` (service does not commit; route
  owns the transaction). Enriching the existing response keeps one response model for the
  surface.
- **Alternatives considered**: A separate response model for the PATCH (rejected: needless
  divergence; the row shape is identical).
