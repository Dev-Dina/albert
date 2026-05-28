# Implementation Plan: Tenant Admin Management

**Branch**: `001-tenant-admin-mgmt` | **Date**: 2026-05-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-tenant-admin-mgmt/spec.md`

## Summary

Add `POST /tenants/{tenant_id}/admins` and `DELETE /tenants/{tenant_id}/admins/{user_id}` to the existing tenancy router. Both endpoints are `tenant_manager`-only. The add path creates a `User` + `TenantMembership(role=tenant_admin)` and rejects suspended/erased tenants. The remove path deletes the membership only, with a last-admin guard that prevents a tenant being left admin-less. Both actions are audit-logged. All logic follows the existing `provisioning.py` pattern.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, SQLAlchemy (async), Pydantic, asyncpg

**Storage**: PostgreSQL — `users`, `tenant_memberships`, `tenants`, `audit_logs` (all existing tables, no migration needed)

**Testing**: pytest + pytest-asyncio (`backend/tests/`)

**Target Platform**: Linux container (Docker — `backend` service)

**Project Type**: Web service (backend API)

**Performance Goals**: Same as existing tenancy endpoints — no new bottlenecks introduced

**Constraints**: `tenant_id` MUST come from the URL path, never the request body. Passwords MUST NOT be logged. Manager MUST NOT gain content read access as a side-effect.

**Scale/Scope**: Two new endpoints, two new service functions, one new test file. No schema migration required.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I — Tenant Isolation | ✅ PASS | `tenant_id` taken from URL path only. New membership scoped to specified tenant only. Manager still cannot read tenant content. |
| II — Layered Architecture | ✅ PASS | Route → provisioning service → audit. No business logic in route handlers. |
| III — Security & Secrets | ✅ PASS | Password bcrypt-hashed, never logged. Audit records actor/action only, not credentials. |
| IV — Test Integrity | ✅ PASS | add-admin, remove-admin, and last-admin guard all covered by tests. |
| V — Spec-Driven Delivery | ✅ PASS | Spec Kit workflow followed. Feature scope is narrow CRUD on existing membership model — does not change RLS, token structure, or auth flow. |

## Project Structure

### Documentation (this feature)

```text
specs/001-tenant-admin-mgmt/
├── plan.md                    ← this file
├── research.md                ← Phase 0
├── data-model.md              ← Phase 1
├── contracts/
│   └── admin-endpoints.md    ← Phase 1
└── tasks.md                   ← Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
backend/
├── app/
│   ├── tenancy/
│   │   └── provisioning.py        ← add add_tenant_admin(), remove_tenant_admin()
│   └── api/routes/
│       └── tenancy.py             ← add POST /{id}/admins, DELETE /{id}/admins/{uid}
└── tests/
    └── test_tenant_admin_mgmt.py  ← new test file
```

**Structure Decision**: Backend-only. No new files except the test. All new code extends existing modules following established patterns.
