# Feature Specification: Tenant Lifecycle Integrity

**Feature Branch**: `009-tenant-lifecycle-integrity`

**Created**: 2026-05-30

**Status**: Draft

**Input**: User description: "Tenant lifecycle integrity: complete right-to-erasure and enforce tenant status."

## Overview

Albert promises two lifecycle guarantees to its business customers: (1) a complete
right-to-erasure — when a tenant is erased, *every* trace of that tenant's data is
destroyed across all stores; and (2) a meaningful tenant status — a tenant that has
been suspended or erased can no longer be used.

Two integrity gaps currently break those promises:

- **Erasure is incomplete.** Two of the tenant-owned data sets are not purged
  explicitly by erasure: escalation records (removed today only as an incidental
  side effect, and never counted in the erasure audit summary) and tenant membership
  links (which survive erasure entirely, leaving a user still associated with an
  "erased" tenant).
- **Tenant status is not enforced.** A tenant's status (active / suspended / erased)
  is honored in only one administrative action. On the everyday paths — admin login,
  admin API access, the public widget handshake, and live chat — status is ignored,
  so an administrator of a suspended or erased tenant can still sign in, operate the
  full admin surface, and keep the chat widget serving traffic. Combined with the
  surviving membership link, an administrator could even repopulate a tenant that was
  supposed to be erased.

This feature closes both gaps and adds a safeguard that prevents the erasure gap from
silently reappearing when new tenant-owned data is introduced later.

## Clarifications

### Session 2026-05-30

- Q: Login authenticates a user (token carries only user_id); how should login enforce
  tenant status for a user who may belong to more than one tenant? → A: Refuse login
  only when a tenant-scoped user has **no active tenant** (every membership is
  non-active). Platform operators (no tenant) and users with at least one active tenant
  can still log in; per-request resolution then blocks any non-active tenant context.
- Q: What HTTP/error semantics should status refusals use, given the no-leak rule? → A:
  Reuse existing generic codes — login refusal returns the generic `401 Invalid
  credentials`; admin principal resolution returns `403` (same shape as "no role");
  the widget handshake and chat return the existing generic widget `401`. No new,
  distinguishable "tenant suspended/erased" error is introduced on any surface.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Erasure leaves nothing behind (Priority: P1)

A platform operator erases a tenant under a data-subject erasure request. After the
operation completes, no data associated with that tenant remains in any store — not
conversations, leads, content, vectors, widget configuration, escalation records, or
the links that associate users with the tenant. The erasure audit summary accounts
for every category of data that was destroyed.

**Why this priority**: Right-to-erasure is a legal/contractual compliance obligation
and the project's top-priority guarantee. Residual tenant data after an erasure is a
direct compliance failure.

**Independent Test**: Seed a disposable tenant with data in every tenant-owned
category (including an escalation and a membership), run erasure, and confirm zero
rows remain for that tenant anywhere and that the audit summary reports each category.

**Acceptance Scenarios**:

1. **Given** a tenant with an open escalation record, **When** the tenant is erased,
   **Then** the escalation record is destroyed **and** the erasure audit summary
   reports the escalation category with its deleted count.
2. **Given** a tenant whose users are linked to it by membership, **When** the tenant
   is erased, **Then** every membership link for that tenant is destroyed **and** the
   audit summary reports the membership category.
3. **Given** two tenants each with escalations and memberships, **When** one tenant is
   erased, **Then** the other tenant's escalations and memberships are completely
   unaffected.
4. **Given** an erasure runs under the production database role (with row-level
   security enforced, no superuser bypass), **When** it completes, **Then** all
   tenant-owned categories — including escalations and memberships — are emptied for
   the target tenant.

---

### User Story 2 - Suspended or erased tenants are locked out (Priority: P1)

An administrator belonging to a tenant that has been suspended or erased attempts to
use the product. Every entry point refuses them: they cannot log in, cannot exercise
the admin API, and the public chat widget for that tenant stops serving. A tenant that
is active behaves exactly as before.

**Why this priority**: Without status enforcement, "suspended" and "erased" are
cosmetic. An erased tenant that can still be operated could be repopulated, defeating
the erasure guarantee; a suspended tenant that still works defeats the suspension.

**Independent Test**: Set a tenant's status to suspended (then erased) and confirm
that login, admin API calls, widget session issuance, and chat are all refused, while
an active tenant is unaffected.

**Acceptance Scenarios**:

1. **Given** an administrator whose only tenant is suspended, **When** they attempt to
   log in, **Then** the attempt is refused with the generic invalid-credentials response.
2. **Given** an administrator whose only tenant is erased, **When** they attempt to log
   in, **Then** the attempt is refused with the generic invalid-credentials response.
2a. **Given** an administrator who belongs to one suspended tenant and one active tenant,
   **When** they log in, **Then** login succeeds, but any request scoped to the suspended
   tenant is refused while requests scoped to the active tenant succeed.
3. **Given** an administrator whose tenant becomes non-active after they already hold a
   valid login token, **When** they call any tenant-admin endpoint, **Then** the call
   is refused.
4. **Given** a visitor on the public site of a suspended or erased tenant, **When** the
   widget attempts to start a session, **Then** the handshake is refused and no chat
   session is created.
5. **Given** a visitor already holding a valid widget session token for a tenant that
   becomes non-active, **When** they send a chat message, **Then** the request is
   refused.
6. **Given** an administrator of an active tenant, **When** they log in and use the
   admin API and widget, **Then** everything works exactly as before this change.
7. **Given** a platform operator (who belongs to no tenant), **When** they log in to
   perform lifecycle actions such as erasure, **Then** their access is unaffected by
   any tenant's status.

---

### User Story 3 - Future tenant data cannot silently leak (Priority: P2)

A developer later adds a new category of tenant-owned data. If they forget to include
it in erasure, an automated safeguard fails loudly, before release, identifying the
uncovered category — so the erasure completeness guarantee cannot silently regress.

**Why this priority**: The two missing data sets in this feature were each introduced
by a later feature without being added to erasure. A standing guard converts a silent,
recurring compliance risk into a caught build failure.

**Independent Test**: Temporarily introduce a tenant-owned data category that erasure
does not cover and confirm the safeguard fails, naming the uncovered category.

**Acceptance Scenarios**:

1. **Given** the current schema, **When** the erasure coverage safeguard runs, **Then**
   it passes because every tenant-owned data category is covered by erasure.
2. **Given** a hypothetical new tenant-owned data category not yet covered by erasure,
   **When** the safeguard runs, **Then** it fails and names the uncovered category.

---

### Edge Cases

- **Already-erased tenant re-erased**: erasing a tenant whose status is already
  "erased" must remain safe and idempotent (no error; nothing to repopulate).
- **Tenant with no escalations / no memberships**: erasure reports a zero count for
  those categories rather than failing or omitting them.
- **Membership link with no surviving tenant or user row**: erasure removes the
  membership link regardless, because it is keyed by tenant.
- **Administrator with memberships in multiple tenants where one is suspended**: status
  enforcement applies to the tenant context actually being acted on; an active tenant
  membership is unaffected by a different tenant's suspension.
- **In-flight widget token at the moment of suspension/erasure**: already-issued tokens
  are time-bounded; chat is refused at the next request once status is non-active.
- **Cross-tenant safety during erasure**: deleting one tenant's data (including the
  newly covered categories) must never touch another tenant's rows.

## Requirements *(mandatory)*

### Functional Requirements

#### Erasure completeness

- **FR-001**: Erasure MUST destroy every row associated with the target tenant across
  all tenant-owned data categories, with no category omitted.
- **FR-002**: Erasure MUST explicitly destroy the target tenant's escalation records
  (rather than relying on an incidental side effect of deleting related data).
- **FR-003**: Erasure MUST destroy every membership link associating any user with the
  target tenant.
- **FR-004**: The erasure audit summary MUST report a per-category deleted-row count for
  every tenant-owned data category it purges, including escalations and memberships.
- **FR-005**: Erasure MUST NOT delete, read, or otherwise affect any other tenant's
  data while purging the target tenant (tenant isolation preserved during erasure).
- **FR-006**: Erasure MUST continue to operate correctly under the production database
  role with row-level security enforced (no reliance on a superuser bypass).
- **FR-007**: Erasure MUST remain write/delete-only with respect to tenant content — it
  MUST NOT read tenant content; only aggregate row counts for the audit summary are
  permitted.

#### Future-proofing guard

- **FR-008**: An automated safeguard MUST verify that every tenant-owned data category
  in the schema is covered by erasure, and MUST fail (naming the uncovered category) if
  any category is not covered.

#### Tenant status enforcement

- **FR-009**: The system MUST treat a tenant as usable only when its status is
  "active". Any other status ("suspended", "erased") MUST be treated as not usable.
- **FR-010**: Login MUST be refused for a tenant-scoped user who has no active tenant
  (every tenant they belong to is non-active). A user who belongs to at least one active
  tenant, and a platform operator (who belongs to no tenant), MUST still be able to log
  in. The refusal MUST use the generic invalid-credentials response (no disclosure that a
  tenant is suspended or erased).
- **FR-011**: Resolution of an administrator's verified identity/tenant context MUST be
  refused when that tenant is non-active, so every tenant-admin API path is closed off
  for non-active tenants.
- **FR-012**: The public widget session handshake MUST be refused for a non-active
  tenant, so no new chat session is created.
- **FR-013**: Live chat (using an already-issued widget session) MUST be refused when
  the tenant is non-active.
- **FR-014**: Platform operators who belong to no tenant (lifecycle/aggregate role) MUST
  retain access regardless of any tenant's status, so erasure and other lifecycle
  actions remain possible.
- **FR-015**: Tenant identity used for every status check MUST be derived from verified
  authentication/session/widget context, never from client-supplied input.
- **FR-016**: Refusals for non-active tenants MUST NOT disclose information that would
  let a caller distinguish "suspended" from "erased" from "no such tenant" beyond what
  is already exposed today (no new information leak). Concretely: login reuses the
  generic `401 Invalid credentials`; admin principal resolution returns `403` of the
  same shape as the existing "no role" refusal; the widget handshake and chat return
  the existing generic widget `401`.

#### Behavior preservation

- **FR-017**: For active tenants, all existing login, admin API, widget handshake, and
  chat behavior MUST be unchanged.
- **FR-018**: The change MUST be code-only — no new database migration and no change to
  existing row-level-security policies.

### Key Entities *(include if feature involves data)*

- **Tenant**: the unit of isolation; carries a lifecycle status of active, suspended, or
  erased. Status is the authority for whether the tenant may be used.
- **Escalation record**: a human-handoff record owned by a tenant; must be purged on
  erasure and counted in the audit summary.
- **Membership link**: associates a user with a tenant and a tenant-scoped role; must be
  purged on erasure so no user remains linked to an erased tenant.
- **Erasure audit summary**: the per-category record of what erasure destroyed; must
  account for every purged category, including escalations and memberships.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After erasing a tenant seeded with data in every tenant-owned category,
  100% of categories — including escalations and memberships — show zero remaining rows
  for that tenant.
- **SC-002**: The erasure audit summary lists a count for 100% of the tenant-owned
  categories it purges, with no category missing.
- **SC-003**: The coverage safeguard detects and names any tenant-owned category not
  covered by erasure (verified by deliberately introducing an uncovered category in a
  test).
- **SC-004**: 100% of login, admin API, widget handshake, and chat attempts that depend
  on a suspended or erased tenant are refused.
- **SC-005**: 100% of equivalent attempts for an active tenant continue to succeed
  (zero regressions for active tenants), and platform operators retain full lifecycle
  access regardless of tenant status.
- **SC-006**: Erasing one tenant leaves a second tenant's data fully intact across every
  category (zero cross-tenant impact).

## Assumptions

- **Non-active = suspended or erased**: any tenant status other than "active" is treated
  as not usable for login, admin, widget, and chat. There is no partial/read-only mode
  for suspended tenants in this feature.
- **Membership deletion is the correct erasure behavior**: the erasure contract is
  "delete all rows WHERE tenant_id = target", so surviving membership links are a
  defect; the fix deletes them. Users themselves (who may belong to other tenants) are
  not deleted by tenant erasure — only the link to the erased tenant.
- **Tenant row is retained as a tombstone**: consistent with current behavior, erasure
  marks the tenant row as "erased" rather than deleting it (for audit), which is why
  child cascades do not fire and explicit deletion is required.
- **Existing tokens are time-bounded**: already-issued login and widget tokens are not
  individually revoked; enforcement happens at the next request/handshake, and widget
  tokens expire on their existing short TTL.
- **Refusal codes follow existing conventions**: status-based refusals reuse the
  product's existing unauthorized/forbidden conventions for each surface and do not
  introduce a new, distinguishable status-specific error.
- **No new database migration**: the tenant status column and all affected tables
  already exist; this is a code-and-tests change only.
- **Scope boundary**: this feature does not add UI for suspending tenants, does not add
  token revocation infrastructure, and does not change row-level-security policies.
