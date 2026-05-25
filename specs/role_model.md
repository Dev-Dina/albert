# Role Model — Specification

**Status**: Draft · **Scope**: roles + access boundaries only (no auth, no models, no routes)

## Purpose

Define the small, fixed set of roles in Albert and what each may and may not do. The role model
exists to support — never to weaken — tenant isolation (see [tenant_model.md](./tenant_model.md)).
There are exactly **three** roles. There is intentionally no general permission matrix and no
configurable RBAC engine.

## Roles

### 1. `tenant_manager` (platform-level)

Operates the platform across tenants. Has **lifecycle** and **aggregate** power, not **content**
access.

- **Can**:
  - create tenants,
  - suspend tenants,
  - trigger tenant erasure,
  - invite the first `tenant_admin` for a tenant,
  - view aggregate usage / cost (counts, totals — not per-record content).
- **Must not**:
  - read tenant conversations, messages, leads, or CMS content,
  - read any private tenant data.

Lifecycle and aggregate access never imply row-level read access to tenant content.

### 2. `tenant_admin` (tenant-level)

Administers a single tenant — their own. Scoped entirely to that tenant.

- **Can** (within own tenant only):
  - manage CMS content,
  - manage widget configuration,
  - manage guardrail configuration,
  - manage leads,
  - manage tenant settings.
- **Cannot**:
  - access any other tenant's data or settings,
  - perform platform-level actions (create/suspend/erase tenants).

Every `tenant_admin` action is bound to their verified `tenant_id`; it can never reach across
tenants.

### 3. `member` / `visitor` (end user)

Uses the product surface only.

- **Can**:
  - use the chat / embedded widget.
- **Cannot**:
  - administer the tenant,
  - access CMS, leads, configs, settings, or any admin function,
  - access any other tenant.

## Cross-cutting rules

- Roles are a **fixed enum** of the three above. No additional roles, no per-action permission
  matrix, no runtime-configurable RBAC.
- Every role decision must **preserve tenant isolation**: a role grant is always evaluated
  together with the verified `tenant_id`. `tenant_admin` / `member` / `visitor` are meaningful
  only within a single tenant; `tenant_manager` is platform-scoped and still cannot read tenant
  content.
- Tenant identity for any decision is derived only from verified auth/session/widget context —
  never from request body, query params, frontend, or LLM output (per the tenant model).
- A higher role does not imply content read access it is not explicitly granted (e.g.
  `tenant_manager` is not a superuser over tenant content).

## Acceptance criteria

- Exactly three roles exist: `tenant_manager`, `tenant_admin`, `member`/`visitor`.
- `tenant_manager` can create, suspend, and erase tenants, invite the first `tenant_admin`, and
  view aggregate usage/cost — and is denied access to tenant conversations, messages, leads, and
  CMS content.
- `tenant_admin` can manage their own tenant's CMS, widgets, guardrail config, leads, and settings,
  and is denied access to any other tenant.
- `member`/`visitor` can use chat/widget only and cannot reach any admin function or other tenant.
- No general permission matrix and no configurable RBAC engine exist.
- Every role check is evaluated against the verified `tenant_id`; no role can bypass tenant
  isolation.

## Out of scope

- Authentication and session handling.
- Token/widget-token issuance and verification.
- Database models, schemas, and migrations.
- API routes, middleware, and authorization code.
- Invitation/onboarding workflow mechanics beyond "invite first `tenant_admin`".
- Any fourth role, sub-roles, or fine-grained permissions.
