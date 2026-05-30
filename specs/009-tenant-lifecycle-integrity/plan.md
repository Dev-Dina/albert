# Implementation Plan: Tenant Lifecycle Integrity

**Branch**: `009-tenant-lifecycle-integrity` | **Date**: 2026-05-30 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/009-tenant-lifecycle-integrity/spec.md`

## Summary

Close two tenant-lifecycle integrity gaps, code-only (no migration, no RLS policy change):

- **Erasure completeness (GAP 1)**: make `erase_tenant` purge every tenant-owned table.
  Add `escalations` (today removed only incidentally via a conversation FK cascade and
  never counted) and `tenant_memberships` (today survives erasure entirely) to the
  explicit delete list so both are destroyed and counted in the audit summary. Add a
  standing coverage guard test that fails if any table with a `tenant_id` column is not
  covered by erasure.
- **Status enforcement (GAP 2)**: enforce `tenant.status == "active"` on the four hot
  paths it is currently missing from — login, admin principal resolution, the widget
  handshake, and chat auth — via a single small tenancy-layer helper, reusing each
  surface's existing generic refusal so no new information leaks.

## Technical Context

**Language/Version**: Python 3.12 (backend), asyncio

**Primary Dependencies**: FastAPI, SQLAlchemy (async), fastapi-users (JWT), asyncpg /
Postgres with `FORCE ROW LEVEL SECURITY`, Redis, MinIO, Vault

**Storage**: PostgreSQL 16 (pgvector). Live tenant-owned tables (16, by `tenant_id`
column): `child_chunks`, `cms_pages`, `content_chunks`, `conversations`, `cost_events`,
`escalations`, `leads`, `messages`, `parent_chunks`, `tenant_guardrail_configs`,
`tenant_memberships`, `widget_allowed_origins`, `widget_configs`,
`widget_guardrail_configs`, `widget_signing_key_versions`, `widgets`.

**Testing**: pytest (`asyncio_mode=auto`). Host runner uses SQLite in-memory
(`uv run --directory backend pytest`); isolation evals run against live Postgres
(`docker compose exec backend uv run pytest evals/isolation/...`).

**Target Platform**: Linux server (Docker Compose). Backend code is baked into the image
— code changes require `docker compose build backend && docker compose up -d
--force-recreate backend`.

**Project Type**: Multi-tenant web service (FastAPI backend + Streamlit admin + widget).

**Performance Goals**: No new hot-path cost beyond one indexed `tenants.status` read per
auth/handshake. Negligible.

**Constraints**: Tenant isolation is absolute (Principle I). Erasure stays
write/delete-only on tenant content. No new migration; no RLS policy change. Tenant
identity always from verified auth/session/widget context, never client input.

**Scale/Scope**: ~5 source files touched, 1 new helper module, ~3 test files. Small PR.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment |
|-----------|------------|
| I. Tenant Isolation Is Absolute (NON-NEGOTIABLE) | **Strengthens it.** Erasure becomes complete (no residual rows); status checks lock out non-active tenants. Cross-tenant safety preserved: erasure deletes are tenant-scoped (RLS context + `WHERE tenant_id`); `tenant_memberships` delete is `WHERE tenant_id = target` only. All status checks derive tenant_id from verified auth/session/widget context, never client input (FR-015). **PASS** |
| II. Layered Architecture & Async Discipline | Status logic centralized in one new `app/tenancy/status.py` helper, consumed by routes/services/deps. All async. Logging, not print. **PASS** |
| III. Security & Secrets Hygiene (NON-NEGOTIABLE) | No secrets touched. No new logging of sensitive data. Refusals reuse generic responses (no new leak, FR-016). **PASS** |
| IV. Test Integrity for Changed Behavior | Every changed path gets a test: erasure of escalations+memberships, coverage guard, and status lockout on all four surfaces + active-tenant non-regression. **PASS** |
| V. Spec-Driven, Phased Delivery | Full risky-feature flow (specify→clarify→plan→tasks→analyze→implement) on branch `009`, small PR. **PASS** |

**Protected files — WARN before editing (Constitution §Security & Operational Constraints):**
This feature edits *auth / tenant-isolation files*, which are protected. The user has
been informed and approved this work. Files: `backend/app/tenancy/erasure.py`,
`backend/app/auth/roles.py`, `backend/app/api/routes/auth.py`, `backend/app/api/deps.py`,
`backend/app/services/widget_session_service.py`, and a new
`backend/app/tenancy/status.py`. **No database migration is added** (the protected
migrations area is deliberately untouched — `tenant.status` and all tables already
exist). **No RLS policy change.** `core/config.py`, `core/security.py`,
`core/logging.py`, `db/session.py` are **not** edited.

**Gate result: PASS** (no unjustified violations; protected-file edits are warned and approved).

## Project Structure

### Documentation (this feature)

```text
specs/009-tenant-lifecycle-integrity/
├── plan.md              # This file
├── spec.md              # Feature spec (+ Clarifications)
├── research.md          # Phase 0 — design decisions
├── data-model.md        # Phase 1 — entities & erasure ordering
├── quickstart.md        # Phase 1 — how to verify live
├── contracts/
│   ├── erasure-summary.md      # erase_tenant() summary contract
│   └── status-enforcement.md   # per-surface refusal contract
└── tasks.md             # Phase 2 — /speckit-tasks (not created here)
```

### Source Code (repository root)

```text
backend/app/
├── tenancy/
│   ├── erasure.py            # EDIT: add escalations + tenant_memberships to delete list
│   └── status.py             # NEW: is_tenant_active(), user_has_active_tenant() helpers
├── auth/
│   └── roles.py              # EDIT: resolve_current_user blocks non-active tenant (403)
├── api/
│   ├── routes/auth.py        # EDIT: login blocks user with no active tenant (generic 401)
│   └── deps.py               # EDIT: get_widget_session blocks non-active tenant (generic 401)
└── services/
    └── widget_session_service.py  # EDIT: exchange() blocks non-active tenant (uniform 403)

backend/tests/
├── test_erasure_coverage.py        # NEW: metadata guard — every tenant_id table covered
└── test_tenant_status_enforcement.py  # NEW: login + resolve_current_user lockout/non-regression

evals/isolation/
└── test_erasure_total.py     # EDIT: seed + assert escalations & memberships purged;
                              #       live information_schema coverage assertion
```

**Structure Decision**: Existing layered backend. The only new module is the
tenancy-layer `status.py` helper, keeping the four enforcement points DRY and auditable
in one place (Principle II). Tests split by execution environment: pure-logic guards and
login/resolution lockout run on the host SQLite runner; full erasure and widget/chat
paths (which need `SET app.current_tenant` / RLS) run in the Postgres isolation evals.

## Phase 0 — Research

See [research.md](research.md). Key resolved decisions:

- **Erasure ordering for accurate counts**: `escalations` must be deleted *before*
  `conversations` so its explicit delete count is non-zero (otherwise the
  `conversation_id` ON DELETE CASCADE empties it first and the summary undercounts).
- **`tenant_memberships` deletion**: it has no RLS, so a `WHERE tenant_id = target`
  delete under the erasure tenant-context works and is correct; users are not deleted.
- **Coverage guard source of truth**: SQLAlchemy `Base.metadata` (deterministic, no DB,
  runs in CI) as the primary guard; a live `information_schema` assertion in the eval as
  a secondary catch for any raw-SQL table not modeled in the ORM.
- **Status helper placement & login semantics**: a single `app/tenancy/status.py`;
  login blocks only users with *no* active tenant (managers and multi-tenant users with
  ≥1 active tenant still log in), per clarification.

## Phase 1 — Design & Contracts

- [data-model.md](data-model.md) — entities, the canonical tenant-owned table set, and
  the erasure delete ordering.
- [contracts/erasure-summary.md](contracts/erasure-summary.md) — the post-change
  `erase_tenant()` summary shape (now includes `postgres.escalations`,
  `postgres.tenant_memberships`).
- [contracts/status-enforcement.md](contracts/status-enforcement.md) — the refusal
  behavior contract for each of the four surfaces.
- [quickstart.md](quickstart.md) — live verification steps on a disposable tenant.

## Complexity Tracking

No constitution violations to justify. The single added abstraction (`status.py`
helper) is the *simpler* alternative to repeating a status query inline at four call
sites, and keeps the enforcement auditable in one place per Principle II.
