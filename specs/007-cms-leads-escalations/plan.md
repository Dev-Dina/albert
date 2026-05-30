# Implementation Plan: CMS Content, Lead Lifecycle & Escalation Capture

**Branch**: `007-cms-leads-escalations` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/007-cms-leads-escalations/spec.md`

## Summary

Close three tenant-scoped admin/data gaps in one focused feature:

1. **CMS** — Give business admins a tenant-scoped API + Streamlit UI to author
   content pages (`cms_pages` table already exists with RLS), replace the
   `ingestion._fetch_content_pages` stub so it reads published pages, and trigger
   a **background** re-index (chunk + embed) on save so the widget agent retrieves
   tenant-authored content within ~1 minute.
2. **Lead lifecycle** — Add a constrained status state machine
   (`new→contacted→qualified→won`, `lost` from any non-terminal, terminal
   `won`/`lost`) with a tenant-scoped update API + admin UI and a
   `status_changed_at` timestamp.
3. **Escalation capture** — Add a tenant-scoped `escalations` table (1:1 with
   conversation, RLS-protected), persist reason/summary in the existing
   `escalate` tool, and add an admin escalations list/detail view.

All three reuse the verified `AdminIdentityDep` (tenant id from membership/JWT,
never client input) which also sets the `app.current_tenant` RLS GUC, giving
application-layer + database-layer (RLS) tenant isolation everywhere.

## Technical Context

**Language/Version**: Python 3.11 (backend, FastAPI + SQLAlchemy async); Streamlit (admin)

**Primary Dependencies**: FastAPI, SQLAlchemy 2.x async, Alembic, asyncpg, Pydantic v2, Streamlit, httpx (admin→backend client). Embeddings via existing `EmbedderAdapter` (Gemini); no new serving deps.

**Storage**: PostgreSQL 16 (pgvector) with FORCE ROW LEVEL SECURITY keyed on `app.current_tenant`. Redis (existing, sessions/cache). No schema changes to Redis.

**Testing**: pytest + pytest-asyncio (backend `backend/tests/`), including cross-tenant red-team tests; Streamlit page tests in `admin/tests/`.

**Target Platform**: Linux containers via Docker Compose (backend, admin, postgres, redis, modelserver, guardrails).

**Project Type**: Multi-service web app (FastAPI backend + Streamlit admin + React widget). This feature touches backend + admin only; widget unchanged.

**Performance Goals**: Content save returns without waiting on embedding; retrievable knowledge converges within ~1 minute (SC-001). Lead status change < 30s admin task (SC-004). No regression to chat latency.

**Constraints**: Tenant isolation is absolute (Principle I). No new heavy deps in serving containers (no torch/transformers). Background indexing must not block the request and must fail observably without losing the saved content. Reuse existing chunk/embed/retrieval pipeline.

**Scale/Scope**: Small per-tenant content volumes (tens–hundreds of pages); body ≤ 100,000 chars. Concurrency low; last-write-wins acceptable.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|-----------|------|--------|
| **I. Tenant Isolation (NON-NEGOTIABLE)** | All new tables RLS-forced on `app.current_tenant`; tenant id only from `AdminIdentityDep`/verified escalation context; retrieval already tenant-filtered; new `escalations` table added to RLS policy set; background re-index runs under a tenant-scoped session. | ✅ PASS |
| **II. Layered Architecture & Async** | New code split into routes / schemas / services / repositories; all DB + network async; logging not print; config centralized. | ✅ PASS |
| **III. Secrets Hygiene (NON-NEGOTIABLE)** | No new secrets. No keys committed. Logs carry ids/status only — never lead PII bodies or escalation free-text at info level beyond existing patterns. | ✅ PASS |
| **IV. Test Integrity for Changed Behavior** | New behavior (CMS CRUD, stub replacement, lead transitions, escalation persistence) each gets unit + integration + cross-tenant tests before "done". | ✅ PASS |
| **V. Spec-Driven, Phased Delivery** | Full risky flow in use (specify→clarify→plan→tasks→analyze→implement); work on branch `007-…`; no building ahead of phase. | ✅ PASS |
| **Ops: lean containers / protected files** | No new serving deps. New Alembic migration is a protected-file class → will warn before adding; touches `ingestion.py` (not protected). No edits to `config.py`/`security.py`/`session.py`/`docker-compose.yml`. | ✅ PASS (with migration warning) |

**Result**: PASS. No violations → Complexity Tracking left empty.

> ⚠️ **Protected-file note**: This feature requires a **new database migration**
> (escalations table + RLS, lead `status_changed_at` column). Migrations are a
> protected class per the constitution — the migration will be called out
> explicitly in tasks and in review, and will not be edited silently.

## Project Structure

### Documentation (this feature)

```text
specs/007-cms-leads-escalations/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (cms.md, leads.md, escalations.md)
└── tasks.md             # Phase 2 output (/speckit-tasks — NOT created here)
```

### Source Code (repository root)

```text
backend/app/
├── api/routes/
│   ├── admin_cms.py                 # NEW: tenant CMS CRUD (AdminIdentityDep)
│   ├── admin_members_and_leads.py   # EDIT: add PATCH /leads/{id} status update
│   └── admin_escalations.py         # NEW: list/detail escalated conversations
├── schemas/
│   ├── admin_cms.py                 # NEW: CmsPageCreate/Update/Response
│   ├── admin_members_and_leads.py   # EDIT: LeadStatusUpdateRequest + status enum
│   └── admin_escalations.py         # NEW: EscalationResponse
├── services/
│   ├── cms_service.py               # NEW: CRUD + schedule background re-index
│   ├── ingestion.py                 # EDIT: _fetch_content_pages reads cms_pages
│   ├── admin_members_leads_service.py # EDIT: update_lead_status + transition rules
│   └── escalation_service.py        # NEW: list/get escalations (read)
├── repositories/
│   ├── cms_repo.py                  # NEW: tenant-scoped page CRUD
│   ├── leads_repo.py                # EDIT: get_for_tenant + update status
│   └── escalation_repo.py           # NEW: upsert + list/get by tenant
├── tools/
│   └── escalate.py                  # EDIT: persist reason/summary (upsert escalation)
├── db/models/
│   ├── cms_page.py                  # EXISTS (no change expected)
│   ├── lead.py                      # EDIT: add status_changed_at
│   └── escalation.py                # NEW: Escalation model
└── ...
backend/alembic/versions/
└── 0015_escalations_and_lead_status.py  # NEW migration (escalations + RLS, lead col)

admin/app/pages_tenant/
├── content.py                       # NEW: CMS authoring page (list/create/edit/delete)
├── leads.py                         # EDIT: lead detail + status transition control
└── escalations.py                   # NEW: escalations list/detail
admin/app/clients/backend_client.py  # EDIT: CMS, lead-status, escalation calls
admin/app/lib/nav.py                 # EDIT: register new pages

backend/tests/                       # CMS CRUD, ingestion stub-replacement, lead
                                     # transitions, escalation persistence + RLS
                                     # cross-tenant red-team additions
admin/tests/                         # new-page forbidden-endpoint + nav tests
```

**Structure Decision**: Multi-service web app. Reuse the established
routes/schemas/services/repositories layering already present under
`backend/app/` and the Streamlit `pages_tenant/` + `backend_client` pattern.
Widget and platform surfaces are untouched.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
