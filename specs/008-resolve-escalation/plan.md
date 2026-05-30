# Implementation Plan: Resolve Escalation

**Branch**: `008-resolve-escalation` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/008-resolve-escalation/spec.md`

## Summary

Make the tenant-admin Escalations view (feature 007, US3) actionable: add a two-state
lifecycle (`open` default / `resolved`) to the existing `escalations` table, with a light
audit trail (`resolved_at`, `resolved_by`). A tenant admin can **resolve** an open escalation
and **reopen** a resolved one from the admin UI; the list defaults to showing open items.

The action is exposed as `PATCH /api/v1/admin/escalations/{conversation_id}` with body
`{"status": "open"|"resolved"}`, scoped through the existing `AdminIdentityDep` (tenant id
from verified membership — never client input) plus the table's existing FORCE ROW LEVEL
SECURITY. Resolving/reopening is **decoupled** from the conversation's own status, and a
cross-tenant attempt returns 404 with no modification.

The only schema change is **additive** — three nullable/defaulted columns via migration
`0016`. The escalations table already has FORCE RLS keyed on `app.current_tenant` (migration
0015), and the new columns don't affect the policy, so **no RLS policy change is required**.

## Technical Context

**Language/Version**: Python 3.11 (backend, FastAPI + SQLAlchemy async); Streamlit (admin)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x async, Alembic, asyncpg, Pydantic v2, Streamlit, httpx (admin→backend client). No new dependencies.

**Storage**: PostgreSQL 16 (pgvector) with FORCE ROW LEVEL SECURITY keyed on `app.current_tenant`. `escalations` table already RLS-forced (0015); this feature adds three columns only.

**Testing**: pytest + pytest-asyncio (backend `backend/tests/`, in-memory SQLite TestClient pattern), including cross-tenant red-team tests; Streamlit page tests in `admin/tests/`.

**Target Platform**: Linux containers via Docker Compose (backend, admin, postgres, redis, …).

**Project Type**: Multi-service web app (FastAPI backend + Streamlit admin + React widget). This feature touches backend + admin only; widget unchanged.

**Performance Goals**: Resolve/reopen is a single sub-second admin action; no impact on chat latency. Escalation volumes are small (tens–hundreds per tenant) so no new index is required.

**Constraints**: Tenant isolation is absolute (Principle I). Additive migration only; no RLS policy change. No secrets/PII in logs (log ids + status only). Resolution must not change conversation status.

**Scale/Scope**: Low concurrency; last-write-wins on status is acceptable. Two-state lifecycle, idempotent transitions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| **I. Tenant Isolation (NON-NEGOTIABLE)** | Write path scoped by `AdminIdentityDep` (tenant from verified membership, never body/path); repo pins `Escalation.tenant_id == tenant_id` on the fetch before any update; table already FORCE RLS as a DB-layer backstop; cross-tenant PATCH → 404 with zero modification (asserted in tests + red-team). `resolved_by` is the *acting* admin (same tenant), not client-supplied. | ✅ PASS |
| **II. Layered Architecture & Async** | New logic split across schemas / route / service / repository / a pure `escalation_lifecycle` module; all DB work async; logging not print; no scattered config. | ✅ PASS |
| **III. Secrets Hygiene (NON-NEGOTIABLE)** | No new secrets. Logs carry `tenant_id`, `conversation_id`, `status`, actor `user_id` only — never escalation free-text. | ✅ PASS |
| **IV. Test Integrity for Changed Behavior** | Every new behavior (resolve, reopen, idempotency, invalid value→422, decoupling, cross-tenant→404) gets a test before "done"; lifecycle unit tests + red-team extension. | ✅ PASS |
| **V. Spec-Driven, Phased Delivery** | Full risky flow (specify→clarify→plan→tasks→analyze→implement) on branch `008-…`; no building ahead of phase; small focused PR. | ✅ PASS |
| **Ops: lean containers / protected files** | No new deps. **New Alembic migration `0016` is a PROTECTED-file class** → warn before adding, call out in tasks + review, never edit silently. No edits to `config.py`/`security.py`/`session.py`/`docker-compose.yml`. | ✅ PASS (with migration warning) |

**Result**: PASS. No violations → Complexity Tracking left empty.

> ⚠️ **Protected-file note**: This feature adds **database migration `0016`**
> (three additive columns on `escalations`). Migrations are a protected class per
> the constitution — `0016` is called out explicitly in tasks and review and will
> not be edited silently. It is additive only and makes **no RLS policy change**.

## Project Structure

### Documentation (this feature)

```text
specs/008-resolve-escalation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── escalations-resolve.md   # Phase 1 output (PATCH contract)
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit-specify)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/app/
├── api/routes/
│   └── admin_escalations.py        # EDIT: add PATCH /{conversation_id}; status filter on list; extend _to_response
├── schemas/
│   └── admin_escalations.py        # EDIT: EscalationStatus enum; status/resolved_at/resolved_by on EscalationResponse; EscalationStatusUpdateRequest
├── services/
│   ├── escalation_service.py       # EDIT: set_escalation_status(...) + EscalationNotFoundError reuse
│   └── escalation_lifecycle.py     # NEW: pure two-state machine (open/resolved), idempotent
├── repositories/
│   └── escalation_repo.py          # EDIT: set_status(...); optional status filter on list_for_tenant
├── db/models/
│   └── escalation.py               # EDIT: add status, resolved_at, resolved_by columns
└── ...
backend/alembic/versions/
└── 0016_escalation_status.py       # NEW migration (3 additive columns; NO RLS change)  [PROTECTED]

admin/app/
├── pages_tenant/escalations.py     # EDIT: status filter (default open) + Resolve/Reopen buttons + show resolver/when
└── clients/backend_client.py       # EDIT: EscalationRow fields; list_escalations(status=...); set_escalation_status(...)

backend/tests/
├── test_escalation_resolve.py      # NEW: resolve/reopen/idempotent/invalid/decoupling/cross-tenant
├── test_escalation_lifecycle.py    # NEW: pure state-machine unit tests
└── redteam/test_cross_tenant_admin.py  # EDIT: add cross-tenant PATCH escalation → 404 + no-mutation assertion
admin/tests/
└── test_escalations_page.py        # NEW (if pattern available): default filter + button affordance smoke
```

**Structure Decision**: Multi-service web app. Reuse the established
routes/schemas/services/repositories layering under `backend/app/` and the Streamlit
`pages_tenant/` + `backend_client` pattern. Mirrors the lead-lifecycle slice from feature 007
(pure `*_lifecycle` module + service transition guard + PATCH route). Widget and platform
surfaces are untouched.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
