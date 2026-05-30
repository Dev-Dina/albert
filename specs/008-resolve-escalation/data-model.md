# Data Model: Resolve Escalation (Phase 1)

## Entity: Escalation (modified)

Existing tenant-owned table `escalations` (1:1 with a conversation, FORCE RLS on
`app.current_tenant` per migration 0015). This feature adds three columns; everything else is
unchanged.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| id | UUID | no | — | PK (existing) |
| tenant_id | UUID | no | — | FK `tenants.id` ON DELETE CASCADE; RLS key (existing) |
| conversation_id | UUID | no | — | FK `conversations.id` ON DELETE CASCADE; UNIQUE (existing) |
| reason | text | no | — | existing |
| summary | text | no | `''` | existing |
| created_at | timestamptz | no | now() | existing |
| updated_at | timestamptz | no | now() | existing; bumped on status change |
| **status** | text | no | `'open'` | **NEW** — `open` \| `resolved` |
| **resolved_at** | timestamptz | yes | NULL | **NEW** — set when resolved, cleared on reopen |
| **resolved_by** | UUID | yes | NULL | **NEW** — acting admin `user_id`; no FK (see research D1) |

### Validation rules

- `status` ∈ {`open`, `resolved`}. Enforced in the app layer: Pydantic `EscalationStatus`
  enum (request) + `escalation_lifecycle.is_valid_status` (service). Invalid value ⇒ 422.
  (No DB CHECK constraint — research D3.)
- `server_default 'open'` back-fills all existing rows on migration; column is `NOT NULL`.
- `resolved_at` / `resolved_by` are non-NULL **iff** `status == 'resolved'` (enforced by the
  repository write, which sets both on resolve and clears both on reopen). This is an
  invariant maintained by `escalation_repo.set_status`, not a DB constraint.

### State transitions (escalation_lifecycle)

```text
open  --resolve-->  resolved        (stamp resolved_at = now, resolved_by = acting admin)
resolved  --reopen-->  open         (clear resolved_at = NULL, resolved_by = NULL)
open  --resolve-->  open (no-op idempotent; nothing to stamp)        # FR-012
resolved --resolve--> resolved      (re-resolve: REFRESH resolved_at/resolved_by)  # FR-012
```

- All transitions between the two valid statuses are permitted (symmetric, FR-002) and
  idempotent (FR-012). There is **no disallowed-transition (409) path** — the only rejection
  is an invalid status *value* (422).
- A status change **never** modifies the linked `conversations.status` (FR-005, decoupled).

### Tenant-isolation invariants

- Every read/write fetches the row with `Escalation.tenant_id == <verified tenant>` first;
  a row owned by another tenant is invisible (returns None ⇒ 404) and never updated (FR-007).
- The acting `resolved_by` user is the verified caller (`AdminIdentity.user_id`), same tenant.
- DB-layer FORCE RLS (0015) is unchanged and remains the fail-closed backstop.

## Relationships

- `Escalation` → `Conversation` (existing, via `conversation_id`). **Read-only** here: the
  conversation's own `status` is not touched by resolve/reopen.
- `resolved_by` references a `users.id` value logically but has **no** FK (research D1).
