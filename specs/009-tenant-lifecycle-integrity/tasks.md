# Tasks: Tenant Lifecycle Integrity

**Feature**: `009-tenant-lifecycle-integrity` | **Plan**: [plan.md](plan.md) | **Spec**: [spec.md](spec.md)

Tests are REQUIRED here (Constitution Principle IV — changed behavior must be covered).
Code-only feature: **no migration**. Edits touch protected auth/tenant-isolation files
(user approved).

**Execution environments**:
- Host (SQLite, fast): `uv run --directory backend pytest <paths>`
- Postgres isolation evals: `docker compose exec backend uv run pytest evals/isolation/<path>`
- After backend edits: `docker compose build backend && docker compose up -d --force-recreate backend`

---

## Phase 1: Setup

- [x] T001 Confirm working branch is `009-tenant-lifecycle-integrity` and the stack is healthy (`git branch --show-current`, `docker compose ps`); capture a baseline `uv run --directory backend pytest -q` run so regressions are attributable.

## Phase 2: Foundational (blocking prerequisites)

No cross-story foundational code is required — the erasure list (US1) and the status
helper (US2) are independent. Proceed directly to the user stories.

---

## Phase 3: User Story 1 — Erasure leaves nothing behind (Priority: P1)

**Goal**: `erase_tenant` explicitly purges `escalations` and `tenant_memberships`, counts
both in the audit summary, with no cross-tenant impact and accurate counts.

**Independent test**: Seed a disposable tenant with an escalation + membership + lead +
conversation, run erasure under the non-superuser RLS role, assert all four → 0 and the
summary reports `postgres.escalations` and `postgres.tenant_memberships`.

### Tests for US1

- [x] T002 [US1] Extend `evals/isolation/test_erasure_total.py`: in `_seed_tenant`, seed an `escalations` row (open, linked to the seeded conversation) and a `tenant_memberships` row (seed a user + membership) for both TENANT_X and TENANT_Y.
- [x] T003 [US1] In `evals/isolation/test_erasure_total.py`, extend the post-erasure assertions to require `escalations` and `tenant_memberships` == 0 for TENANT_X, == 1 for TENANT_Y (cross-tenant survival), and assert `summary["postgres.escalations"] == 1` and `summary["postgres.tenant_memberships"] == 1`. Add `escalations` and `tenant_memberships` to the `_ALL_TENANT_TABLES` list used by the non-superuser RLS test.

### Implementation for US1

- [x] T004 [US1] In `backend/app/tenancy/erasure.py`, add `"escalations"` to `_TENANT_TABLES` positioned **immediately before `"conversations"`** (so the explicit delete runs before the conversation FK cascade and the count is accurate — research D1), and add `"tenant_memberships"` at the end of `_TENANT_TABLES`. Update the module docstring/inline comments to note escalations ordering and that `tenant_memberships` has no RLS (deletes via `WHERE tenant_id`).
- [x] T005 [US1] Run `docker compose exec backend uv run pytest evals/isolation/test_erasure_total.py -v` and confirm all three erasure tests pass (escalations + memberships purged, counted, cross-tenant intact, non-superuser RLS path).

**Checkpoint**: erasure is complete and counted; US1 independently verifiable.

---

## Phase 4: User Story 2 — Suspended or erased tenants are locked out (Priority: P1)

**Goal**: enforce `tenant.status == "active"` on login, admin principal resolution, widget
handshake, and chat auth — reusing each surface's generic refusal; platform managers and
active tenants unaffected.

**Independent test**: set a tenant non-active and confirm login (sole-tenant admin),
admin API, widget handshake, and chat are refused, while an active tenant and a platform
manager are unaffected.

### Implementation — shared helper (do first)

- [x] T006 [US2] Create `backend/app/tenancy/status.py` with async `is_tenant_active(db, tenant_id) -> bool` (reads `tenants.status`, platform table/no RLS, returns `status == "active"`) and `user_has_active_tenant(db, user_id) -> bool` (EXISTS join `tenant_memberships`→`tenants` where tenant active). Use logging, not print; no secrets.

### Tests for US2 (host, SQLite)

- [x] T007 [P] [US2] Create `backend/tests/test_tenant_status_enforcement.py`: tests for `app/tenancy/status.py` helpers and for `roles.resolve_current_user` — (a) tenant-scoped principal with non-active tenant → 403 same shape as "No role assigned."; (b) active tenant → resolves normally; (c) platform manager → unaffected regardless of any tenant status.
- [x] T008 [P] [US2] In `backend/tests/test_tenant_status_enforcement.py`, add login-path tests for `auth.login`: (a) sole-tenant admin whose tenant is suspended/erased → generic 401; (b) admin with one suspended + one active tenant → login succeeds; (c) platform manager → login succeeds regardless; (d) active-tenant admin → unchanged success.

### Implementation — enforcement points

- [x] T009 [US2] In `backend/app/auth/roles.py` `resolve_current_user`, after the membership is selected (tenant-scoped branch only), call `is_tenant_active(db, membership.tenant_id)`; if false raise the existing 403 ("No role assigned." shape). Leave the platform-manager early return untouched (FR-014). Keep tenant_memberships as the no-RLS read it already is.
- [x] T010 [US2] In `backend/app/api/routes/auth.py` `login`, inject the DB session, and after `authenticate` (and the existing `is_active` check) refuse with the existing `_invalid_credentials` when the user is **not** a platform manager AND `user_has_active_tenant(db, user.id)` is false. Managers and users with ≥1 active tenant proceed.
- [x] T011 [US2] In `backend/app/services/widget_session_service.py` `exchange`, after resolving `lookup.tenant_id` (and before/within the tenant_context block), call `is_tenant_active(session, lookup.tenant_id)`; if false raise `WidgetSessionError("tenant not active")` so the route returns the existing uniform 403 (no new leak).
- [x] T012 [US2] In `backend/app/api/deps.py` `get_widget_session`, after the token claims are verified and before `yield`, call `is_tenant_active(db, claims tenant_id)`; if false raise the existing generic `_widget_credentials_exc` (401).

### Tests for US2 — widget & chat (Postgres eval / redteam)

- [x] T013 [US2] Add a widget+chat status-lockout test to the isolation/redteam suite (e.g. `backend/tests/redteam/test_cross_tenant_admin.py` or a new `evals/isolation/test_tenant_status_lockout.py`, whichever matches existing infra): a non-active tenant's `exchange` raises (uniform 403) and `get_widget_session` with a valid-but-non-active-tenant token is refused (401); an active tenant still issues a session and serves chat. Run under Postgres so `SET app.current_tenant` works.

**Checkpoint**: all four surfaces enforce status; active tenants and managers unaffected.

---

## Phase 5: User Story 3 — Future tenant data cannot silently leak (Priority: P2)

**Goal**: a standing guard fails (naming the table) if any `tenant_id` table is not
covered by erasure.

**Independent test**: temporarily add an uncovered tenant-owned table/model and confirm
the guard fails naming it; current schema passes.

### Tests for US3

- [x] T014 [P] [US3] Create `backend/tests/test_erasure_coverage.py`. Factor the check into a small pure helper, e.g. `uncovered_tenant_tables(tenant_tables: set[str], covered: set[str]) -> set[str]` returning the set difference. **Positive test**: import `app.db.models` to populate `Base.metadata`, compute `{table.name for table in Base.metadata.tables.values() if 'tenant_id' in table.columns}`, and assert `uncovered_tenant_tables(<that set>, set(erasure._TENANT_TABLES) | set(erasure._OPTIONAL_LEGACY_TABLES))` is empty; on failure the assertion message MUST name the uncovered table(s). **Negative test (SC-003)**: pass a synthetic tenant-owned table name (e.g. `"surprise_new_tenant_table"`) not in the coverage set and assert the helper reports exactly that name — proving the guard fails loudly when a future `tenant_id` table is added uncovered. Runs on host, no DB.
- [x] T015 [US3] In `evals/isolation/test_erasure_total.py`, add a live coverage assertion: query `information_schema.columns` for tables with a `tenant_id` column in `public` and assert each is in the erasure coverage set (names any gap). Secondary catch for raw-SQL tables not in the ORM.

**Checkpoint**: coverage guard green on current schema; proven to fail on an uncovered table.

---

## Phase 6: Polish & Cross-Cutting

- [x] T016 Rebuild and recreate the backend image (`docker compose build backend && docker compose up -d --force-recreate backend`) so the edited code is live.
- [x] T017 Run the full host suite (`uv run --directory backend pytest -q`) and the isolation evals (`docker compose exec backend uv run pytest evals/isolation -v`); confirm green and no regressions vs the T001 baseline.
- [x] T018 Lint: `uv run --directory backend ruff check app evals tests` (fix any new findings; match existing style/import hoisting conventions).
- [x] T019 Live verification per [quickstart.md](quickstart.md): on a disposable tenant, show erasure leaves escalations + memberships at 0 with summary counts, and a second tenant intact; then show status lockout on login/admin/widget/chat for a suspended tenant and recovery after reactivate. Clean up the disposable tenant.
  - DONE (erasure): disposable-tenant live run confirmed escalations + tenant_memberships counted (1 each) and purged (0); cleaned up.
  - Status lockout verified decisively by tests (test_auth login gate, test_tenant_status_enforcement resolution gate, test_widget_status_lockout handshake+chat) rather than a live HTTP demo, to avoid mutating the shared demo tenants. The live recipe remains in quickstart.md for manual use.

---

## Dependencies & ordering

- **Setup (T001)** → everything.
- **US1 (T002–T005)**: tests T002–T003 before impl T004; T005 verifies. Independent of US2.
- **US2 (T006–T013)**: helper T006 before enforcement T009–T012 and tests T007–T008/T013. T009–T012 touch different files → parallelizable after T006. Independent of US1.
- **US3 (T014–T015)**: T014 independent; T015 builds on US1's final table list (run after T004).
- **Polish (T016–T019)**: after US1+US2+US3 code is complete.

## Parallel execution examples

- After T006: run T009, T010, T011, T012 in parallel (separate files), with T007/T008 alongside.
- T014 [P] and T007 [P]/T008 [P] are independent host tests; can be authored in parallel.
- US1 and US2 are independent tracks and can proceed concurrently by two workers.

## Implementation strategy

- **MVP = US1 + US2** (both P1): completes the erasure compliance fix and closes the
  auth lockout gap. US3 (P2) is the durability guard and lands right after US1.
- Deliver incrementally: US1 verified green → US2 verified green → US3 guard green →
  polish (rebuild + full suite + lint + live verification).
