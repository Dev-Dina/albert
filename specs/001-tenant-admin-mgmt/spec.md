# Feature Specification: Tenant Admin Management

**Feature Branch**: `001-tenant-admin-mgmt`

**Created**: 2026-05-26

**Status**: Draft

**Input**: Add two tenant admin management endpoints: POST /tenants/{tenant_id}/admins to add a new tenant_admin to an existing tenant, and DELETE /tenants/{tenant_id}/admins/{user_id} to remove a specific admin from a tenant. Both endpoints are tenant_manager only. Adding an admin creates a new User + TenantMembership (role=tenant_admin). Removing an admin deletes the TenantMembership but NOT the User row. Both actions must be audit-logged. Cannot remove the last admin from a tenant (guard required). Cannot add an admin if the tenant is suspended or erased.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Add Admin to Existing Tenant (Priority: P1)

A platform operator (tenant_manager) needs to onboard a second administrator for an existing tenant — for example, when a business grows and needs a second point of contact, or when an existing admin leaves and a replacement must be added before the old one is removed.

**Why this priority**: Without this, a tenant with only one admin is permanently stuck if that admin needs to be replaced or the business scales. It is the core capability this feature delivers.

**Independent Test**: A tenant_manager can call the add-admin endpoint with a valid email + password and receive back the new user_id, with the new user visible in the tenant's audit log.

**Acceptance Scenarios**:

1. **Given** an active tenant with one existing admin, **When** the tenant_manager posts a valid email and password, **Then** a new user account is created, assigned the tenant_admin role for that tenant, and the action is recorded in the audit log.
2. **Given** a tenant with status `suspended`, **When** the tenant_manager attempts to add an admin, **Then** the request is rejected with a clear error indicating the tenant is not active.
3. **Given** a tenant with status `erased`, **When** the tenant_manager attempts to add an admin, **Then** the request is rejected.
4. **Given** an email address already registered in the system, **When** the tenant_manager attempts to add that email as a new admin, **Then** the request is rejected with a conflict error.

---

### User Story 2 — Remove Admin from Tenant (Priority: P1)

A platform operator needs to revoke a specific admin's access to a tenant — for example, when an employee leaves the business or their access must be rotated. The user's platform account is preserved (they may belong to other tenants or be re-invited later); only their membership in this tenant is removed.

**Why this priority**: Admin lifecycle management (add + remove) must ship together as a complete capability. Removing without adding would leave tenants stuck; adding without removing creates a no-offboarding gap.

**Independent Test**: A tenant_manager can call the remove-admin endpoint for a known user_id; the user can no longer authenticate as an admin for that tenant, and the action is recorded in the audit log.

**Acceptance Scenarios**:

1. **Given** a tenant with two admins, **When** the tenant_manager removes one admin by user_id, **Then** that user's membership is deleted, the user account itself is preserved, and the action is audit-logged.
2. **Given** a tenant with exactly one admin, **When** the tenant_manager attempts to remove that last admin, **Then** the request is rejected with an error indicating at least one admin must remain.
3. **Given** a user_id that is not an admin of the specified tenant, **When** the tenant_manager attempts to remove them, **Then** the request is rejected with a not-found error.
4. **Given** a valid removal, **When** the removed admin attempts to log in and use their old token, **Then** they receive a 403 (their role/tenant context no longer resolves).

---

### Edge Cases

- What happens when the same email is added as admin to a tenant where they are already an admin? → Rejected with a conflict error (duplicate membership).
- What happens when tenant_id in the path does not exist? → 404 for both add and remove endpoints.
- What happens if a non-manager (tenant_admin or member) calls these endpoints? → 403 Forbidden.
- What if the user being removed is the actor themselves? → Allowed only if at least one other admin remains; blocked if they are the last admin.
- What if `user_id` belongs to a `tenant_manager` or `member` role in another tenant? → The add endpoint always creates a fresh `tenant_admin` membership scoped to the target tenant; the user's other memberships are unaffected.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Only users with the `tenant_manager` role MUST be permitted to add or remove tenant admins.
- **FR-002**: Adding an admin MUST create a new `User` record and a `TenantMembership` record with role `tenant_admin` scoped to the specified tenant.
- **FR-003**: The system MUST reject add-admin requests if the target tenant status is anything other than `active` (i.e., `suspended` or `erased`).
- **FR-004**: The system MUST reject add-admin requests if the supplied email is already registered in the platform.
- **FR-005**: Removing an admin MUST delete the `TenantMembership` record only; the `User` row MUST NOT be deleted.
- **FR-006**: The system MUST reject remove-admin requests if the target user is the last remaining `tenant_admin` for that tenant.
- **FR-007**: The system MUST reject remove-admin requests if the specified `user_id` does not hold a `tenant_admin` membership for the specified tenant.
- **FR-008**: Both add and remove actions MUST be recorded in the audit log with the actor's `user_id`, the target `tenant_id`, the affected `user_id`, and a timestamp.
- **FR-009**: The `tenant_manager` MUST NOT gain read access to tenant content (conversations, leads, CMS pages) as a side-effect of these endpoints.
- **FR-010**: `tenant_id` for the new admin membership MUST be taken from the URL path parameter — never from the request body.

### Key Entities

- **User**: A platform account identified by email. Created on add-admin; preserved (not deleted) on remove-admin.
- **TenantMembership**: Binds a User to a Tenant with a specific role. Created on add-admin; deleted on remove-admin.
- **AuditLog**: Records every manager action with actor, target tenant, affected user, action name, and timestamp.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A tenant_manager can add a second admin to any active tenant in a single API call with no additional steps required.
- **SC-002**: A tenant_manager can remove any non-last admin from a tenant in a single API call.
- **SC-003**: Attempting to remove the last admin is rejected 100% of the time with a clear error — no tenant is ever left admin-less.
- **SC-004**: Every add and remove action produces a verifiable audit log entry containing actor, target tenant, affected user, and timestamp.
- **SC-005**: A removed admin's authentication token is rejected on all tenant-scoped endpoints immediately after removal (no grace period or cache window).
- **SC-006**: Adding an admin to a suspended or erased tenant is rejected 100% of the time.

---

## Assumptions

- A newly added admin receives credentials via the API response (email + password returned to the calling manager). No invitation email is sent — this is out of scope for this phase, consistent with the existing `provision_tenant` behavior.
- A `User` may have memberships in multiple tenants with different roles (e.g., `tenant_admin` for Tenant A and `tenant_admin` for Tenant B). Each membership is independent.
- The removed admin's existing JWT tokens are not explicitly invalidated server-side (no token blacklist exists yet). Security relies on short token expiry (`JWT_EXPIRE_MINUTES` setting). This is an accepted limitation for this phase.
- Only one membership per (tenant, user) pair is enforced by a unique constraint already present in the schema.
- The tenant_manager performing these actions does not need to know or supply the new admin's `tenant_id` in the body — it is always taken from the path.
