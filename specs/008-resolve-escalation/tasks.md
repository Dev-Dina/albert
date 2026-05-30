---
description: "Task list for Resolve Escalation"
---

# Tasks: Resolve Escalation

**Input**: Design documents from `specs/008-resolve-escalation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/escalations-resolve.md

**Tests**: REQUIRED. Constitution Principle IV mandates tests for changed behavior, and
Principle I requires cross-tenant red-team coverage. Test tasks are included in every story
(write them first; they must FAIL before implementation).

**Organization**: Tasks grouped by user story — US1 Resolve (P1), US2 Reopen (P2),
US3 Status filter (P2) — for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3
- Repo-relative file paths included.

## Path Conventions

Multi-service web app: backend at `backend/app/`, backend tests at `backend/tests/`,
Streamlit admin at `admin/app/`, admin tests at `admin/tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm working baseline before changes.

- [X] T001 Confirm branch `008-resolve-escalation` checked out and stack healthy (`docker compose ps` all healthy; `docker compose exec backend alembic current` shows head `0015`).
- [X] T002 [P] Re-skim `backend/app/services/lead_lifecycle.py`, `backend/app/services/admin_members_leads_service.py` (`update_lead_status`), `backend/app/api/routes/admin_members_and_leads.py` (`PATCH /leads/{id}`), and `backend/app/repositories/escalation_repo.py` to confirm the patterns mirrored in this feature (pure lifecycle module, service transition guard, route commit, tenant-pinned repo fetch).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Additive schema + model + pure lifecycle module that every story depends on.

**⚠️ CRITICAL**: US1/US2/US3 cannot begin until this phase is complete.

> ⚠️ **PROTECTED FILE**: T003 adds a new Alembic **migration** (`0016`, protected class per
> the constitution). Call it out explicitly in review; do not edit existing migrations. It is
> additive only and makes **no RLS policy change**.

- [X] T003 Create migration `backend/alembic/versions/0016_escalation_status.py` (revision `0016_escalation_status`, down_revision `0015_escalations_and_lead_status`): `ALTER TABLE escalations ADD COLUMN status text NOT NULL server_default 'open'`, `ADD COLUMN resolved_at timestamptz NULL`, `ADD COLUMN resolved_by uuid NULL`. **No** RLS/policy statements. Full `downgrade()` drops the three columns. Mirror the file-header docstring style of `0015`.
- [X] T004 [P] Extend `Escalation` model in `backend/app/db/models/escalation.py`: add `status: Mapped[str]` (`default="open"`, `server_default="open"`, `nullable=False`), `resolved_at: Mapped[datetime | None]`, `resolved_by: Mapped[uuid.UUID | None]` (use `GUID`) per data-model.md.
- [X] T005 [P] Create pure state machine `backend/app/services/escalation_lifecycle.py` mirroring `lead_lifecycle.py`: `ESCALATION_STATUSES = ("open", "resolved")`; `is_valid_status(s)`; `can_transition(current, target)` returning True for any valid target (symmetric + idempotent, FR-002/FR-012); `allowed_targets(current)`.
- [X] T006 [P] [Unit tests] Create `backend/tests/test_escalation_lifecycle.py` mirroring `test_lead_lifecycle.py`: valid statuses, `open↔resolved` allowed both directions, idempotent same-state allowed, invalid value rejected by `is_valid_status`. (Run on host: `uv run --directory backend pytest tests/test_escalation_lifecycle.py`.)
- [X] T007 Apply migration locally and verify additive + RLS-unchanged: `docker compose build backend && docker compose up -d --force-recreate backend && docker compose exec backend alembic upgrade head`; assert `\d+ escalations` shows `status` (NOT NULL, default `'open'`), `resolved_at`, `resolved_by`; assert `pg_class` still shows `relrowsecurity=t, relforcerowsecurity=t` for `escalations` (policy unchanged).

**Checkpoint**: Schema + model + lifecycle ready — US1/US2/US3 unblocked.

---

## Phase 3: User Story 1 — Resolve an open escalation (Priority: P1) 🎯 MVP

**Goal**: A tenant admin can resolve an open escalation; it records resolver + time, persists,
and the conversation's own status is untouched.

**Independent Test**: Resolve an open escalation in the admin UI (or via PATCH); confirm
`status='resolved'`, `resolved_by`=caller, `resolved_at` set, persists across reload, and the
conversation status is unchanged.

### Tests for US1 (write first — must FAIL before T012–T015)

- [X] T008 [P] [US1] In `backend/tests/test_escalation_resolve.py` (new, mirror the SQLite `TestClient` + `_override_get_db` pattern from `backend/tests/test_escalation.py`): test that `PATCH /api/v1/admin/escalations/{conv}` with `{"status":"resolved"}` returns 200 with `status=resolved`, `resolved_by`=acting admin, `resolved_at` non-null, and the row persists.
- [X] T009 [P] [US1] In the same file: test **decoupling** — after resolve, the linked `conversations.status` is unchanged (still `escalated`) (FR-005, SC-005).
- [X] T010 [P] [US1] In the same file: test **invalid value** — `{"status":"bogus"}` → 422 and the row is unchanged (FR-008, SC-006).
- [X] T011 [P] [US1] In the same file: test **cross-tenant** — Tenant B `PATCH` of Tenant A's conversation → 404, and Tenant A's escalation remains `open`/unresolved (FR-007, SC-004).

### Implementation for US1

- [X] T012 [US1] Extend `backend/app/schemas/admin_escalations.py`: add `EscalationStatus(str, Enum)` (`open`, `resolved`); add `status: str`, `resolved_at: datetime | None`, `resolved_by: UUID | None` to `EscalationResponse`; add `EscalationStatusUpdateRequest(BaseModel)` with `status: EscalationStatus`.
- [X] T013 [US1] Add `set_status(session, *, escalation, status, resolved_by)` to `backend/app/repositories/escalation_repo.py`: set `escalation.status`; if `resolved` set `resolved_at=now(utc)`, `resolved_by=resolved_by`; else clear both to `None`; bump `updated_at`; `flush()`. Does not commit.
- [X] T014 [US1] Add `set_escalation_status(session, *, tenant_id, conversation_id, new_status, resolved_by)` to `backend/app/services/escalation_service.py`: fetch via `escalation_repo.get_for_tenant` (tenant-pinned) → `None` raises `EscalationNotFoundError`; guard `escalation_lifecycle.is_valid_status`; call `escalation_repo.set_status`; `logger.info` with `tenant_id`/`conversation_id`/`status`/actor only (no free-text). Return `(escalation, conversation_status)`. Does not commit.
- [X] T015 [US1] Add `PATCH /{conversation_id}` to `backend/app/api/routes/admin_escalations.py`: body `EscalationStatusUpdateRequest`, `AdminIdentityDep`; call `svc.set_escalation_status(..., resolved_by=identity.user_id)`; map `EscalationNotFoundError`→404; `await db.commit()`; return enriched `_to_response`. Extend `_to_response` to include `status`/`resolved_at`/`resolved_by`.
- [X] T016 [US1] Admin client: in `admin/app/clients/backend_client.py` add `status`, `resolved_at`, `resolved_by` to `EscalationRow` (+ `_escalation_from_json`); add `set_escalation_status(self, conversation_id, *, status) -> EscalationRow` (PATCH).
- [X] T017 [US1] Admin UI: in `admin/app/pages_tenant/escalations.py` render the current `status` per row and add a **Resolve** button on open escalations that calls `client.set_escalation_status(conv, status="resolved")` then `st.rerun()`; show `resolved_by`/`resolved_at` for resolved rows. Use `handle_backend_error` like `leads.py`.
- [X] T018 [US1] Run US1 tests on host: `uv run --directory backend pytest tests/test_escalation_resolve.py -q` (T008–T011 pass).

**Checkpoint**: Resolve works end-to-end (MVP). US2/US3 build on the same write path.

---

## Phase 4: User Story 2 — Reopen a resolved escalation (Priority: P2)

**Goal**: A tenant admin can reopen a resolved escalation; it returns to `open` and clears the
resolver fields.

**Independent Test**: Reopen a resolved escalation; confirm `status='open'`, `resolved_at`/
`resolved_by` cleared, and conversation status unchanged.

### Tests for US2 (write first — must FAIL before T020)

- [X] T019 [P] [US2] In `backend/tests/test_escalation_resolve.py`: test reopen — `PATCH {"status":"open"}` on a resolved escalation → 200 `status=open`, `resolved_at`/`resolved_by` both null (FR-004); and **idempotent re-resolve** refreshes `resolved_at`/`resolved_by` (FR-012); reopen leaves conversation status unchanged.

### Implementation for US2

- [X] T020 [US2] Add a **Reopen** button to resolved rows in `admin/app/pages_tenant/escalations.py` calling `client.set_escalation_status(conv, status="open")` then `st.rerun()`. (Backend reopen path already implemented in US1 via the symmetric `set_status`; no new backend code — verify T019 passes: `uv run --directory backend pytest tests/test_escalation_resolve.py -q`.)

**Checkpoint**: Full open↔resolved lifecycle usable from the UI.

---

## Phase 5: User Story 3 — Filter escalations by status (Priority: P2)

**Goal**: The Escalations page defaults to showing open items and can switch to resolved/all.

**Independent Test**: Load the page → only open shown; switch filter to resolved → only
resolved; switch to all → both.

### Tests for US3 (write first — must FAIL before T022–T024)

- [X] T021 [P] [US3] In `backend/tests/test_escalation_resolve.py`: seed one open + one resolved escalation for the tenant; assert `GET /api/v1/admin/escalations?status=open` returns only the open one, `?status=resolved` only the resolved one, and no `status` param returns both (FR-009).

### Implementation for US3

- [X] T022 [US3] Add an optional `status` filter to `escalation_repo.list_for_tenant` (filter `Escalation.status == status` when provided, always in addition to the `tenant_id` filter).
- [X] T023 [US3] Thread `status` through `escalation_service.list_escalations` and the `GET /api/v1/admin/escalations` route (`status_filter: str | None = Query(default=None, alias="status")`, mirroring the leads list route).
- [X] T024 [US3] Admin UI: add a status filter selectbox to `admin/app/pages_tenant/escalations.py` defaulting to **open** (options `open`/`resolved`/`all`; `all`→None), and pass it to `client.list_escalations(status=...)`. Update `list_escalations` in `backend_client.py` to accept `status`.
- [X] T025 [US3] Run US3 tests on host: `uv run --directory backend pytest tests/test_escalation_resolve.py -q` (T021 passes).

**Checkpoint**: Default-open view + resolved/all filtering complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T026 [P] Extend `backend/tests/redteam/test_cross_tenant_admin.py`: add a cross-tenant `PATCH /api/v1/admin/escalations/{CONV_A}` (`{"status":"resolved"}`) → assert 404, and assert Tenant A's escalation is still `open` (no mutation) in the consolidated isolation gate.
- [X] T027 [P] If an admin escalations page test pattern exists (check `admin/tests/`), add `admin/tests/test_escalations_page.py` smoke: default filter is open + Resolve/Reopen affordance renders. Skip if no comparable Streamlit test harness exists for the page.
- [X] T028 Run full suites on host with no regressions: `uv run --directory backend pytest -q` and `uv run --directory admin pytest -q`.
- [X] T029 Live verification per `quickstart.md` §3–§5: resolve an escalation in the browser as `admin-acme@example.com` (persists across reload, conversation status unchanged), reopen it, and confirm `admin-beta@example.com` gets 404 on Acme's conversation with zero DB mutation.
- [X] T030 Final review pass: confirm migration `0016` is additive/no-RLS-change, no `tenant_id`/`resolved_by` accepted from client input, no PII in logs, and the PR is small/focused. Suggest the commit/PR commands (do not run git unless asked).

---

## Dependencies & Execution Order

- **Setup (P1)** → **Foundational (P2: T003–T007)** block everything.
- **US1 (P3)** is the MVP and must land first (it implements the shared write path).
- **US2 (P4)** depends on US1's backend `set_status` (reopen is the symmetric path) — only adds
  a UI button + a reopen/idempotency test.
- **US3 (P5)** depends only on Foundational + the existing list endpoint; independent of US2.
- **Polish (P6)** after the stories.

## Parallel Opportunities

- T004, T005, T006 [P] (model / lifecycle / lifecycle unit test — different files).
- T008–T011 [P] (US1 tests — same new file, write together before implementation).
- T026, T027 [P] (red-team + admin page test — different files).

## Implementation Strategy

- **MVP = Phase 1 + Phase 2 + Phase 3 (US1)**: resolve works end-to-end with tests.
- Then US2 (reopen UI) and US3 (filter) are small independent increments.
- Tests are written first within each story and must fail before implementation (Principle IV).
