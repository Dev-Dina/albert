# Tasks: Tenant Admin Management

**Input**: Design documents from `specs/001-tenant-admin-mgmt/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Organization**: Tasks grouped by user story. No setup or migration phase — this feature extends existing modules with no new tables.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared dependencies)
- **[Story]**: User story label (US1 = Add Admin, US2 = Remove Admin)

---

## Phase 1: Foundational (Blocking Prerequisite)

**Purpose**: Extend `provisioning.py` with the two new service functions. Both user story endpoint tasks depend on this phase.

**⚠️ CRITICAL**: Route tasks (US1 + US2) cannot begin until T001 and T002 are complete.

- [x] T001 Add `add_tenant_admin(db, actor_user_id, tenant_id, email, password)` to `backend/app/tenancy/provisioning.py` — checks tenant status active, checks email uniqueness, creates User + TenantMembership(role=tenant_admin), audit-logs `tenant.admin.add`
- [x] T002 Add `remove_tenant_admin(db, actor_user_id, tenant_id, user_id)` to `backend/app/tenancy/provisioning.py` — verifies membership exists, counts remaining tenant_admins, guards against removing last admin, deletes membership (NOT user), audit-logs `tenant.admin.remove`

**Checkpoint**: Both service functions exist, raise `ValueError` on all guard conditions, and audit-log on success.

---

## Phase 2: User Story 1 — Add Admin to Existing Tenant (Priority: P1) 🎯

**Goal**: `POST /tenants/{tenant_id}/admins` is callable by a tenant_manager and correctly provisions a new admin.

**Independent Test**: POST the endpoint with a valid manager token + new email → 201 response with `admin_user_id`. POST again with a suspended tenant → 409. POST with a duplicate email → 409.

### Implementation for User Story 1

- [x] T003 [US1] Add `AddAdminRequest` and `AddAdminResponse` Pydantic schemas to `backend/app/api/routes/tenancy.py`
- [x] T004 [US1] Add `POST /{tenant_id}/admins` route to `backend/app/api/routes/tenancy.py` — `TenantManagerDep`, calls `add_tenant_admin()`, maps `ValueError` to HTTP 409, commits, returns `AddAdminResponse`
- [x] T005 [US1] Import `add_tenant_admin` in `backend/app/api/routes/tenancy.py`

**Checkpoint**: `POST /tenants/{id}/admins` returns 201 for valid input, 409 for suspended/erased tenant and duplicate email, 403 for non-manager callers.

---

## Phase 3: User Story 2 — Remove Admin from Tenant (Priority: P1)

**Goal**: `DELETE /tenants/{tenant_id}/admins/{user_id}` removes the membership without deleting the user account, and refuses to remove the last admin.

**Independent Test**: DELETE the endpoint for one of two admins → 200, membership gone, user account still exists. DELETE the last admin → 409. DELETE a non-existent membership → 404.

### Implementation for User Story 2

- [x] T006 [US2] Add `RemoveAdminResponse` Pydantic schema to `backend/app/api/routes/tenancy.py`
- [x] T007 [US2] Add `DELETE /{tenant_id}/admins/{user_id}` route to `backend/app/api/routes/tenancy.py` — `TenantManagerDep`, calls `remove_tenant_admin()`, maps `ValueError` to HTTP 404 or 409 based on message, commits, returns `RemoveAdminResponse`
- [x] T008 [US2] Import `remove_tenant_admin` in `backend/app/api/routes/tenancy.py`

**Checkpoint**: `DELETE /tenants/{id}/admins/{uid}` returns 200 for valid removal, 409 for last-admin guard, 404 for unknown membership, 403 for non-manager callers.

---

## Phase 4: Tests

**Purpose**: Cover all new behavior per Constitution Principle IV.

- [x] T009 [P] Create `backend/tests/test_tenant_admin_mgmt.py` with `test_add_admin_success` — provisions a tenant, calls `add_tenant_admin()`, asserts new membership exists with role `tenant_admin`
- [x] T010 [P] Add `test_add_admin_rejects_suspended_tenant` to `backend/tests/test_tenant_admin_mgmt.py` — suspends tenant first, asserts `ValueError` raised
- [x] T011 [P] Add `test_add_admin_rejects_erased_tenant` to `backend/tests/test_tenant_admin_mgmt.py`
- [x] T012 [P] Add `test_add_admin_rejects_duplicate_email` to `backend/tests/test_tenant_admin_mgmt.py`
- [x] T013 [P] Add `test_remove_admin_success` — two admins, remove one, assert membership deleted, user row intact
- [x] T014 [P] Add `test_remove_last_admin_blocked` — single admin on tenant, assert `ValueError` raised
- [x] T015 [P] Add `test_remove_nonexistent_membership_raises` — user_id not a member of that tenant

**Checkpoint**: All 7 tests pass. `docker compose exec backend uv run pytest backend/tests/test_tenant_admin_mgmt.py -v`

---

## Phase 5: Polish

- [x] T016 [P] Verify `GET /tenants/{tenant_id}` response is consistent after adding/removing admins (no stale data)
- [x] T017 Confirm audit log entries for `tenant.admin.add` and `tenant.admin.remove` appear in `GET /tenants/{tenant_id}/audit`

---

## Dependencies & Execution Order

```
T001, T002  (provisioning service functions — Phase 1, sequential, T001 before T002)
    ↓
T003–T005   (US1 route — Phase 2, T003 before T004, T005 can be with T003)
T006–T008   (US2 route — Phase 3, T006 before T007, T008 can be with T006)
    ↓
T009–T015   (tests — Phase 4, all [P] — run in parallel)
    ↓
T016–T017   (polish — Phase 5)
```

### Parallel Opportunities

```
# Phase 1: sequential (T001 must precede T002 — remove guard reads membership count which add also writes)
T001 → T002

# Phase 2 + 3: can overlap after T001/T002 are done
T003, T005  ← parallel (both touch tenancy.py but different symbols)
T004        ← after T003
T006, T008  ← parallel
T007        ← after T006

# Phase 4: all test tasks parallel
T009, T010, T011, T012, T013, T014, T015
```

---

## Implementation Strategy

### MVP First

1. Complete Phase 1 (T001–T002): service functions
2. Complete Phase 2 (T003–T005): add-admin endpoint
3. **Validate**: POST /tenants/{id}/admins returns 201
4. Complete Phase 3 (T006–T008): remove-admin endpoint
5. **Validate**: DELETE /tenants/{id}/admins/{uid} returns 200 / 409

### Full Delivery

1. Phases 1–3 → both endpoints working
2. Phase 4 → all tests green
3. Phase 5 → audit log verified

---

## Notes

- No database migration — existing `users`, `tenant_memberships`, `tenants`, `audit_logs` tables used as-is
- `tenant_id` MUST always come from the URL path, never the request body (Principle I)
- Password MUST be bcrypt-hashed before storage, never logged (Principle III)
- `ValueError` messages must be distinct enough for the route layer to map them to the correct HTTP status code (404 vs 409)
