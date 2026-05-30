# Feature Specification: Resolve Escalation

**Feature Branch**: `008-resolve-escalation`

**Created**: 2026-05-30

**Status**: Draft

**Input**: User description: "Add the ability to RESOLVE an escalation from the tenant-admin UI. Today the escalations admin view (feature 007, US3) is read-only. Add a resolve/reopen capability with an `open`/`resolved` status, a light audit trail (who/when), decoupled from the conversation's own status, tenant-scoped via verified admin membership."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Resolve an open escalation (Priority: P1)

A tenant admin reviewing the Escalations page sees a conversation the agent handed off to
a human. After they (or a teammate) have followed up with the visitor, they mark the
escalation **resolved** so it drops out of the default working list and the team knows it
has been handled. The system records who resolved it and when.

**Why this priority**: This is the core gap the feature closes — today admins can read an
escalation but have no way to mark it handled, so the list grows without bound and there is
no signal of which handoffs are still outstanding. Resolving is the minimum viable slice.

**Independent Test**: Sign in as a tenant admin with at least one open escalation, click
**Resolve** on it, and confirm it moves to the `resolved` state, records the acting admin
and a timestamp, and no longer appears under the default (open-only) filter. Fully testable
on its own and delivers the feature's primary value.

**Acceptance Scenarios**:

1. **Given** an open escalation in my tenant, **When** I resolve it, **Then** its status
   becomes `resolved`, the resolved-by (my user) and resolved-at (current time) are recorded,
   and the change persists across a page reload.
2. **Given** an escalation I just resolved, **When** I view the Escalations page with the
   default filter, **Then** the resolved escalation is hidden (default shows open only).
3. **Given** an escalation, **When** I resolve it, **Then** the underlying conversation's own
   status is unchanged.

---

### User Story 2 - Reopen a resolved escalation (Priority: P2)

An admin realizes a handoff marked resolved actually still needs attention (the visitor
replied, or it was resolved by mistake). They **reopen** it so it returns to the active
working list.

**Why this priority**: Mistakes and re-engagements happen; without reopen, an
incorrectly-resolved escalation is lost from the working view permanently. It is secondary
to being able to resolve at all, but completes a usable lifecycle.

**Independent Test**: Filter the Escalations page to show resolved items, click **Reopen** on
one, and confirm it returns to `open` and the resolved-by/resolved-at fields are cleared.

**Acceptance Scenarios**:

1. **Given** a resolved escalation in my tenant, **When** I reopen it, **Then** its status
   becomes `open` and the resolved-by/resolved-at fields are cleared (back to empty).
2. **Given** a resolved escalation, **When** I reopen it, **Then** the underlying
   conversation's own status is unchanged.

---

### User Story 3 - Filter escalations by status (Priority: P2)

An admin wants to focus on outstanding handoffs by default, but can also review what has
already been resolved.

**Why this priority**: A status filter is what makes resolve/reopen useful day-to-day —
without it the resolved state has no visible effect on the list. It pairs tightly with US1.

**Independent Test**: Toggle the status filter between open, resolved, and all, and confirm
the list contents match the selected status, defaulting to open.

**Acceptance Scenarios**:

1. **Given** my tenant has both open and resolved escalations, **When** I load the page,
   **Then** only open escalations are shown by default.
2. **Given** the page, **When** I switch the filter to `resolved`, **Then** only resolved
   escalations are shown; **When** I switch to `all`, **Then** both are shown.

---

### Edge Cases

- **Cross-tenant attempt**: An admin in Tenant B attempts to resolve or reopen an escalation
  belonging to Tenant A. The system MUST behave as though the escalation does not exist (no
  modification, no existence disclosure) and return a not-found outcome.
- **Invalid status value**: A request to set a status other than `open` or `resolved` is
  rejected as invalid input; the escalation is unchanged.
- **Idempotent transition**: Resolving an already-resolved escalation (or reopening an
  already-open one) leaves it in the requested state without error. Re-resolving refreshes
  the resolved-by/resolved-at to the latest actor and time.
- **Missing escalation**: Resolving an escalation for a conversation that has no escalation
  record in the caller's tenant returns a not-found outcome.
- **Concurrent re-escalation**: If the agent re-escalates a conversation (updating its
  reason/summary) the resolution status is independent and is not implicitly reset by the
  re-escalation. (Status changes only via the admin resolve/reopen action.)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Each escalation MUST carry a lifecycle status with exactly two values, `open`
  and `resolved`, defaulting to `open` for all existing and newly-created escalations.
- **FR-002**: A tenant admin MUST be able to transition an escalation from `open` to
  `resolved` (resolve) and from `resolved` to `open` (reopen). Both directions are permitted.
- **FR-003**: When an escalation is resolved, the system MUST record the acting admin's
  identity (resolved-by) and the time of resolution (resolved-at).
- **FR-004**: When an escalation is reopened, the system MUST clear the resolved-by and
  resolved-at fields (return them to empty).
- **FR-005**: Resolving or reopening an escalation MUST NOT change the status of the
  underlying conversation; the two lifecycles are independent.
- **FR-006**: The acting tenant MUST be derived from the admin's verified membership, never
  from any client-supplied value in the request body, query, or path.
- **FR-007**: An admin MUST NOT be able to resolve, reopen, read, or otherwise affect an
  escalation belonging to another tenant; such an attempt MUST return a not-found outcome
  with no existence disclosure and no modification.
- **FR-008**: A request to set a status outside the allowed set MUST be rejected as invalid
  input and leave the escalation unchanged.
- **FR-009**: The Escalations admin view MUST expose a status filter that defaults to showing
  only `open` escalations, with the ability to view `resolved` or all.
- **FR-010**: The Escalations admin view MUST present a Resolve action on each open
  escalation and a Reopen action on each resolved escalation, and reflect the current status
  of each escalation.
- **FR-011**: The escalation status and its resolved-by/resolved-at MUST be visible to the
  admin (so a resolved item shows it was resolved).
- **FR-012**: Status transitions MUST be idempotent: requesting the current status succeeds
  and leaves the escalation in that status (re-resolving refreshes resolved-by/resolved-at).
- **FR-013**: The data change MUST be applied under the same tenant-isolation guarantees as
  all other escalation data (row-level isolation at the database, plus app-layer tenant
  scoping on every read and write).

### Key Entities *(include if feature involves data)*

- **Escalation**: Captured human-handoff context for a conversation (one per conversation,
  owned by a tenant). Gains a **status** (`open` / `resolved`, default `open`), a
  **resolved-at** timestamp (empty until resolved), and a **resolved-by** reference to the
  admin user who resolved it (empty until resolved). Its existing reason/summary/timestamps
  and tenant ownership are unchanged.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A tenant admin can resolve an open escalation in a single action from the
  Escalations page, and the change persists across a page reload.
- **SC-002**: After resolving, the escalation no longer appears under the default (open-only)
  view, and appears when the filter is switched to resolved or all.
- **SC-003**: A resolved escalation can be reopened in a single action and returns to the
  default open view, with its prior resolution record cleared.
- **SC-004**: 100% of cross-tenant resolve/reopen attempts return a not-found outcome and
  result in zero modification to the other tenant's data (verified by an automated
  cross-tenant test).
- **SC-005**: Resolving or reopening an escalation never alters the underlying conversation's
  status (verified by an automated test).
- **SC-006**: An invalid status value is rejected as invalid input with the escalation left
  unchanged (verified by an automated test).

## Assumptions

- Only the two statuses `open` and `resolved` are needed; no intermediate states (e.g.,
  "in progress") are in scope for v1.
- Reopen is permitted (symmetric lifecycle), mirroring the project's existing lead lifecycle
  which allows backward-reachable transitions; this was an explicit product decision.
- Resolution is decoupled from conversation status by explicit product decision — resolving
  an escalation is an admin triage action, not a change to the conversation itself.
- The light audit trail (resolved-by/resolved-at on the row) is sufficient for v1; a separate
  immutable audit-log entry is not required for this action.
- Resolution notes/comments, bulk resolve, and notifications are out of scope for v1.
- The acting admin is a `tenant_admin` of exactly one tenant (the existing admin surface
  model); the verified membership supplies the tenant scope.
- The existing escalations storage already enforces tenant row-level isolation; this feature
  adds fields only and relies on that existing isolation contract unchanged.
