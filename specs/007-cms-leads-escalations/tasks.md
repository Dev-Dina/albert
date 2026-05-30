---

description: "Task list for CMS Content, Lead Lifecycle & Escalation Capture"
---

# Tasks: CMS Content, Lead Lifecycle & Escalation Capture

**Input**: Design documents from `specs/007-cms-leads-escalations/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: REQUIRED. Constitution Principle IV mandates tests for changed
behavior, and Principle I requires cross-tenant red-team coverage. Test tasks are
therefore included in every story (write them first; they must FAIL before
implementation).

**Organization**: Tasks grouped by user story (US1 CMS = P1, US2 Leads = P2,
US3 Escalations = P3) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3
- Absolute repo-relative file paths included.

## Path Conventions

Multi-service web app: backend at `backend/app/`, backend tests at
`backend/tests/`, Streamlit admin at `admin/app/`, admin tests at `admin/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm working baseline before changes.

- [X] T001 Confirm branch `007-cms-leads-escalations` is checked out and stack is healthy (`docker compose ps` all healthy; `docker compose exec backend alembic current` shows head `0014`). ✓ branch correct; all services healthy; Alembic at `0014_revoke_public_widget_lookup (head)`.
- [X] T002 [P] Skim `backend/app/services/ingestion.py`, `backend/app/tools/escalate.py`, `backend/app/db/models/{cms_page,lead,conversation}.py`, and `backend/alembic/versions/0003_tenant_owned_tables_rls.py` to confirm the assumptions in research.md (cms_pages + RLS exist; chunk pipeline keyed on content_id; escalate drops reason/summary). ✓ confirmed. **Note for later phases**: `ChunkRepo` lives in `backend/app/repos/chunk_repo.py` (import `from app.repos.chunk_repo import ChunkRepo`; class takes `db`; `delete_chunks_for_content(content_id, tenant_id)` exists). New admin repos go in `backend/app/repositories/` (matches `leads_repo`/`members_repo` convention) — `repos/` and `repositories/` are distinct dirs.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared schema + models needed by US2 and US3. (US1/CMS needs no
migration — `cms_pages` already exists — so US1 may proceed in parallel with this
phase.)

**⚠️ CRITICAL**: US2 and US3 cannot begin until this phase is complete.

> ⚠️ **PROTECTED FILE**: T003 adds a new Alembic **migration** (protected class
> per the constitution). Call it out explicitly in review; do not edit existing
> migrations.

- [X] T003 Create migration `backend/alembic/versions/0015_escalations_and_lead_status.py`: create `escalations` table (`id, tenant_id FK→tenants CASCADE, conversation_id FK→conversations CASCADE UNIQUE, reason text NOT NULL, summary text NOT NULL default '', created_at, updated_at`); `ENABLE`+`FORCE ROW LEVEL SECURITY` with the `app.current_tenant` tenant-isolation policy (USING + WITH CHECK, mirroring 0003); `ALTER TABLE leads ADD COLUMN status_changed_at timestamptz NULL`. Provide full `downgrade()` (drop column, policy, table). ✓ Created (down_revision 0014).
- [X] T004 [P] Create `Escalation` model in `backend/app/db/models/escalation.py` (fields per data-model.md; `UniqueConstraint(conversation_id)`); register it in `backend/app/db/models/__init__.py`. ✓
- [X] T005 [P] Add `status_changed_at: Mapped[datetime | None]` column to `backend/app/db/models/lead.py`. ✓
- [X] T006 Apply migration locally and verify RLS: `docker compose exec backend alembic upgrade head`, then assert `escalations` shows `relrowsecurity=t, relforcerowsecurity=t` and the `status_changed_at` column exists on `leads`. ✓ Required a backend image rebuild (code baked into image, not volume-mounted). Verified: alembic head `0015`; escalations RLS `true,true`; policy `escalations_tenant_isolation`; `uq_escalations_conversation`; `leads.status_changed_at timestamptz`; albert_app auto-grants `DELETE,INSERT,SELECT,UPDATE`.

**Checkpoint**: Schema ready — US2 and US3 unblocked. US1 may already be in flight.

---

## Phase 3: User Story 1 - Author content the agent answers from (Priority: P1) 🎯 MVP

**Goal**: Tenant-scoped CMS CRUD whose published pages flow into the existing
RAG pipeline via background re-index, so the widget agent answers from authored
content.

**Independent Test**: As Acme admin, create a page with distinctive text → within
~1 min the Acme widget answers a related question from it; edit changes the
answer; delete removes it; Beta cannot see/retrieve it.

### Tests for User Story 1 (write first, must FAIL)

- [X] T007 [P] [US1] Integration test for CMS CRUD endpoints in `backend/tests/test_admin_cms.py` (create/list/get/update/delete happy paths + 422 empty/oversized body + 409 slug conflict). ✓
- [X] T008 [P] [US1] Cross-tenant test in `backend/tests/test_admin_cms.py` (Tenant B GET/PUT/DELETE of Tenant A page_id → 404; no existence disclosure). ✓
- [X] T009 [P] [US1] Test that `ingestion._fetch_content_pages` returns published pages for the tenant in `backend/tests/test_ingestion.py` (replace the stub-returns-[] expectation; unpublished excluded; tenant_id from param not row), plus a delete-removes-chunks assertion. ✓

### Implementation for User Story 1

- [X] T010 [P] [US1] Create schemas in `backend/app/schemas/admin_cms.py`: `CmsPageCreate`, `CmsPageUpdate`, `CmsPageResponse` (body 1..100000 non-empty after strip; title 1..200; optional slug; `is_published` defaults to `true` on create per spec v1 — no draft UI). ✓
- [X] T011 [P] [US1] Create `backend/app/repositories/cms_repo.py`: tenant-scoped `list_pages`, `get_page`, `create_page`, `delete_page`, `slug_exists`, and `get_published_pages(tenant_id, content_ids)` returning `[{content_id, body}]` for **published** pages (used by ingestion). Slug derivation (`slugify`) + uniqueness handling. ✓
- [X] T012 [US1] Create `backend/app/services/cms_service.py`: CRUD orchestration over `cms_repo`; on create/update schedule background re-index; on delete schedule chunk removal (`ChunkRepo.delete_chunks_for_content`). Typed errors (`CmsPageNotFound`, `CmsSlugConflict`). ✓
- [X] T013 [US1] Background re-index (`_reindex_page`/`_remove_page_chunks` in `cms_service.py`) opens its OWN tenant-scoped session (sets `app.current_tenant` GUC), deletes stale chunks then calls `ingest_tenant_content(tenant_id, content_ids=[page_id], db, embedder)`; wraps errors, logs ids/status only, never reuses the request session. ✓
- [X] T014 [US1] Replace the stub in `ingestion.py::_fetch_content_pages` to call `cms_repo.get_published_pages(...)` (published only); tenant_id from the injected parameter, never rows. ✓
- [X] T015 [US1] Create routes in `backend/app/api/routes/admin_cms.py` (`/api/v1/admin/cms/pages` GET/POST, `/{page_id}` GET/PUT/DELETE) using `AdminIdentityDep`; inject `BackgroundTasks` + `request.app`; map service errors → 404/409/422. ✓
- [X] T016 [US1] Register the CMS router in `backend/app/main.py`. ✓
- [X] T017 [P] [US1] Add CMS client methods + `CmsPageRow` in `admin/app/clients/backend_client.py` (list/create/get/update/delete pages). ✓
- [X] T018 [US1] Create Streamlit content authoring page `admin/app/pages_tenant/content.py` (list + create + edit + delete; empty-state); register it in `admin/app/lib/nav.py` (tenant surface 8→9 entries). ✓
- [X] T019 [P] [US1] Update admin nav test for the Content page in `admin/tests/test_nav.py`; the forbidden-endpoint guard auto-covers `content.py`. ✓
- [X] T020 [US1] Tests green: backend `test_admin_cms.py` + `test_ingestion.py` (17 passed); full backend suite **226 passed**; admin nav/forbidden/client tests **28 passed**. Live SC-001 retrieval e2e is bundled into Phase 6 quickstart (T046).

**Checkpoint**: US1 fully functional and independently testable (MVP).

---

## Phase 4: User Story 2 - Progress a lead through its lifecycle (Priority: P2)

**Goal**: Tenant-scoped lead status state machine with view + transition API and
admin UI; only valid transitions accepted; `status_changed_at` recorded.

**Independent Test**: As Acme admin, open a `new` lead, advance it along allowed
states (persists + `status_changed_at` set), and confirm a disallowed transition
returns 409 and Beta cannot touch an Acme lead.

### Tests for User Story 2 (write first, must FAIL)

- [ ] T021 [P] [US2] Test the transition map (pure function) in `backend/tests/test_lead_lifecycle.py` (every allowed/terminal/disallowed pair).
- [ ] T022 [P] [US2] Integration test in `backend/tests/test_lead_lifecycle.py` for `GET /api/v1/admin/leads/{id}` and `PATCH` (allowed → 200 + status_changed_at; disallowed → 409 unchanged; unknown value → 422).
- [ ] T023 [P] [US2] Cross-tenant test (Beta GET/PATCH of Acme lead → 404) in `backend/tests/test_lead_lifecycle.py`.

### Implementation for User Story 2

- [ ] T024 [P] [US2] Add `LeadStatus` enum + `LeadStatusUpdateRequest` and extend `LeadResponse` with `status_changed_at` in `backend/app/schemas/admin_members_and_leads.py`.
- [ ] T025 [US2] Extend `backend/app/repositories/leads_repo.py` with `get_for_tenant(session, tenant_id, lead_id)` and `update_status(session, lead, new_status)` (sets `status_changed_at=now()`), keeping tenant scoping non-negotiable.
- [ ] T026 [US2] Add transition map + `update_lead_status(...)` (validate target ∈ allowed set, else raise transition error) and `get_lead(...)` to `backend/app/services/admin_members_leads_service.py`. (depends on T024, T025)
- [ ] T027 [US2] Add `GET /api/v1/admin/leads/{lead_id}` and `PATCH /api/v1/admin/leads/{lead_id}` to `backend/app/api/routes/admin_members_and_leads.py` (`AdminIdentityDep`; map errors → 404/409/422; include `status_changed_at` in responses). (depends on T026)
- [ ] T028 [P] [US2] Add lead status-update client method in `admin/app/clients/backend_client.py`.
- [ ] T029 [US2] Update `admin/app/pages_tenant/leads.py` with a lead detail view + status control offering only valid next states (terminal states disable changes). (depends on T028)
- [ ] T030 [US2] Run US2 tests green: `docker compose exec backend pytest backend/tests/test_lead_lifecycle.py -q`; manual check via quickstart §2.

**Checkpoint**: US1 and US2 both independently functional.

---

## Phase 5: User Story 3 - Capture and review escalations (Priority: P3)

**Goal**: Persist escalation reason/summary (1:1 per conversation, upsert) and a
tenant-scoped admin view to list/read escalated conversations.

**Independent Test**: Drive an Acme conversation to escalation → row stored with
reason/summary; admin escalations view shows it; re-escalation keeps one updated
row; reason-only escalation stores empty summary; Beta never sees it.

### Tests for User Story 3 (write first, must FAIL)

- [ ] T031 [P] [US3] Unit test for escalation upsert in `backend/tests/test_escalation.py` (insert on first; update reason/summary/updated_at on re-escalation; single row enforced; reason-only → summary='').
- [ ] T032 [P] [US3] Integration test for `GET /api/v1/admin/escalations` and `/{conversation_id}` in `backend/tests/test_escalation.py` (list shows reason+summary+conversation_status; 404 for non-tenant). Include a **real-path** test: drive an escalation through the widget-chat flow (tenant GUC set as in production) and assert the `escalations` row persists under RLS — not only a direct `escalate(...)` call.
- [ ] T033 [P] [US3] Cross-tenant test (Beta cannot list/get Acme escalations → not shown / 404) in `backend/tests/test_escalation.py`.

### Implementation for User Story 3

- [ ] T034 [P] [US3] Create `backend/app/repositories/escalation_repo.py`: `upsert(session, tenant_id, conversation_id, reason, summary)`, `list_for_tenant(session, tenant_id, limit, offset)` (join conversations for status, newest updated_at first), `get_for_tenant(session, tenant_id, conversation_id)`.
- [ ] T035 [US3] Update `backend/app/tools/escalate.py` to upsert an `escalations` row (via repo) after ensuring the conversation row exists, using the verified `tenant_id`/`conversation_id` from session context; keep return shape; keep no-db degradation path. **RLS note**: `escalations` is FORCE-RLS, so the insert/update requires `app.current_tenant` to be set on the chat-path DB session — confirm the widget-chat flow already sets the tenant GUC (it must, since it writes RLS-forced `conversations`/`messages`), and the upsert must run within that same tenant context (never set tenant from client input). (depends on T034)
- [ ] T036 [P] [US3] Create `backend/app/schemas/admin_escalations.py` with `EscalationResponse` (conversation_id, reason, summary, conversation_status, created_at, updated_at).
- [ ] T037 [US3] Create read service `backend/app/services/escalation_service.py` (`list_escalations`, `get_escalation`) over the repo. (depends on T034, T036)
- [ ] T038 [US3] Create routes `backend/app/api/routes/admin_escalations.py` (`GET /api/v1/admin/escalations`, `GET /{conversation_id}`) with `AdminIdentityDep`; register router in `backend/app/main.py`. (depends on T037)
- [ ] T039 [P] [US3] Add escalation client methods in `admin/app/clients/backend_client.py`.
- [ ] T040 [US3] Create Streamlit `admin/app/pages_tenant/escalations.py` (list + detail with reason/summary; empty-state); register in `admin/app/lib/nav.py`. (depends on T039)
- [ ] T041 [P] [US3] Add admin forbidden-endpoint/nav test for escalations page in `admin/tests/test_pages_tenant_forbidden_endpoints.py` and `admin/tests/test_nav.py`.
- [ ] T042 [US3] Run US3 tests green: `docker compose exec backend pytest backend/tests/test_escalation.py -q`; manual check via quickstart §3.

**Checkpoint**: All three stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Cross-story isolation hardening, full validation, hygiene.

- [ ] T043 [P] Extend `backend/tests/redteam/cross_tenant_demo.py` with cms_pages, leads (status update), and escalations cross-tenant assertions, plus an RLS fail-closed check (empty/wrong `app.current_tenant` → no rows) for `escalations`.
- [ ] T044 [P] Logging hygiene review (Principle III): confirm no lead PII bodies, content bodies, or escalation free-text logged at info; ids/status only across `cms_service.py`, `escalate.py`, `admin_members_leads_service.py`.
- [ ] T045 Run the full suites: `docker compose exec backend pytest backend/tests -q` and admin tests; fix regressions.
- [ ] T046 Execute `specs/007-cms-leads-escalations/quickstart.md` end-to-end against the local stack (all three stories + isolation checks; verify SC-001 ≤1 min convergence).
- [ ] T047 [P] If the temporary `http://localhost:8000` entry in Acme's `widget_allowed_origins` is still present from the gap-1 workaround, confirm it is unrelated to this feature and leave a note (do not change auth config here).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: after Setup. Blocks US2 and US3 (schema). Does NOT block US1.
- **US1 (Phase 3)**: after Setup; independent of Phase 2 (cms_pages pre-exists).
- **US2 (Phase 4)**: after Phase 2 (needs `status_changed_at`).
- **US3 (Phase 5)**: after Phase 2 (needs `escalations` table).
- **Polish (Phase 6)**: after all desired stories.

### User Story Dependencies

- US1, US2, US3 are mutually independent and independently testable. Shared touch
  points (`backend/app/main.py` router registration, `backend_client.py`,
  `nav.py`) are additive — sequence edits to those shared files to avoid
  conflicts (they are NOT marked [P] where they touch a shared file).

### Within Each User Story

- Tests first (must FAIL) → schemas/models → repository → service → routes →
  router registration → admin UI → green tests.

### Parallel Opportunities

- T004/T005 parallel (different model files).
- All `[P]` test tasks within a story run together.
- With staff: US1 (no Phase 2 dependency) can run fully in parallel with Phase 2;
  US2 and US3 in parallel once Phase 2 is done — coordinating only the shared
  `main.py`/`backend_client.py`/`nav.py` edits.

---

## Parallel Example: User Story 1

```bash
# Tests first (parallel):
Task: "Integration test for CMS CRUD in backend/tests/test_admin_cms.py"   # T007
Task: "Cross-tenant CMS test in backend/tests/test_admin_cms.py"           # T008
Task: "_fetch_content_pages reads published pages in backend/tests/test_ingestion.py"  # T009

# Then parallel scaffolding:
Task: "CMS schemas in backend/app/schemas/admin_cms.py"        # T010
Task: "cms_repo in backend/app/repositories/cms_repo.py"       # T011
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. (US1 needs no migration) → 3. Phase 3 US1 → STOP & VALIDATE
   (the CMS unblocks real RAG content — the highest-value slice) → demo.

### Incremental Delivery

1. Setup → Foundational (migration) ready.
2. US1 (CMS) → test → demo (MVP).
3. US2 (Leads) → test → demo.
4. US3 (Escalations) → test → demo.
5. Polish (cross-tenant red-team + full suite + quickstart).

---

## Notes

- [P] = different files, no dependency on an incomplete task.
- New migration (T003) is a PROTECTED file class — flag in review, don't touch existing migrations.
- Tenant id always from `AdminIdentityDep` / verified escalation context — never request body/query/path.
- Background re-index uses its OWN tenant-scoped session (request session is closed by response time).
- Commit after each task or logical group (only when the user asks — do not run Git automatically).
- Run `/speckit.analyze` before `/speckit.implement` (risky feature).
