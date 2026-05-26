# Research: Tenant Admin Management

## Decision 1: Service Layer Location

**Decision**: Extend `backend/app/tenancy/provisioning.py` with `add_tenant_admin()` and `remove_tenant_admin()`.

**Rationale**: The existing `provision_tenant()` function already creates `User` + `TenantMembership` in the same file. Adding admin management here keeps all tenant lifecycle logic co-located and avoids a new module.

**Alternatives considered**: New `admin.py` service file — rejected because the feature is small and the pattern already exists in `provisioning.py`.

---

## Decision 2: Last-Admin Guard Implementation

**Decision**: Count `tenant_admin` memberships for the target tenant using a `SELECT COUNT(*)` before deleting. If count == 1, raise `ValueError`.

**Rationale**: Atomic check within the same transaction. SQLAlchemy async session holds the transaction open across the count + delete, so no TOCTOU race condition under normal usage.

**Alternatives considered**: Database-level constraint (trigger or check) — rejected because it adds migration complexity for a guard that is straightforward in application code and already tested.

---

## Decision 3: User Account on Remove

**Decision**: `DELETE` only the `TenantMembership` row. The `User` row is preserved.

**Rationale**: A user may belong to multiple tenants. Deleting the user account would affect other tenants and is an irreversible platform action outside the scope of tenant admin management. The spec explicitly states the user row is NOT deleted.

**Alternatives considered**: Soft-delete / deactivate user — rejected as out of scope for this phase.

---

## Decision 4: Tenant Status Gate on Add

**Decision**: Check `tenant.status == 'active'` before creating any rows. Reject with 409 if suspended or erased.

**Rationale**: Adding an admin to a suspended tenant would create a user with valid credentials for a tenant they cannot actually use. Adding to an erased tenant is a data integrity error. Both cases should fail fast.

**Alternatives considered**: Allow adding to suspended tenants (admin can log in once reactivated) — rejected because it creates confusion and inconsistency with the provisioning flow which also requires an active tenant.

---

## Decision 5: Response Shape for Add Admin

**Decision**: Return `{ admin_user_id, email, tenant_id }`. Do NOT return the password in the response.

**Rationale**: The password is set by the manager who calls the endpoint — they already know it. Returning it in the response would log it in access logs. The existing `provision_tenant` endpoint also does not echo the password back.

**Alternatives considered**: Return a one-time token for the admin to set their own password — out of scope for this phase.

---

## Decision 6: Duplicate Membership Guard

**Decision**: Rely on the existing `UNIQUE(tenant_id, user_id)` constraint in `tenant_memberships`. Catch the database integrity error and return HTTP 409.

**Rationale**: The constraint already exists in the schema (from migration 0001). No need to add an application-layer pre-check. A single database round-trip is more efficient and race-condition-safe.
