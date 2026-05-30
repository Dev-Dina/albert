# Contract: tenant status enforcement

Helper (`app/tenancy/status.py`):
- `is_tenant_active(db, tenant_id) -> bool` — `True` iff `tenants.status == "active"`.
  Reads the platform `tenants` table (no RLS); no `app.current_tenant` needed.
- `user_has_active_tenant(db, user_id) -> bool` — `True` iff the user has ≥1 membership
  whose tenant is active.

Tenant identity for every check is derived from verified context, never client input
(FR-015).

## Per-surface behavior

### S1 — Login (`POST /auth/login`)
- **Given** credentials valid AND user is a platform manager → **issue token** (FR-014).
- **Given** credentials valid AND user is tenant-scoped AND has ≥1 active tenant →
  **issue token**.
- **Given** credentials valid AND user is tenant-scoped AND has **no** active tenant →
  **401 `Invalid credentials`** (generic; no disclosure — FR-010, FR-016).
- **Given** credentials invalid → unchanged 401.

### S2 — Admin principal resolution (`resolve_current_user`, behind `get_current_user`)
- **Given** platform manager → unchanged (no tenant, no status check) (FR-014).
- **Given** tenant-scoped principal whose resolved tenant is active → unchanged.
- **Given** tenant-scoped principal whose resolved tenant is non-active → **403**, same
  shape as the existing "No role assigned." refusal (FR-011, FR-016). This closes every
  tenant-admin API path (incl. `get_admin_tenant_id`).

### S3 — Widget handshake (`widget_session_service.exchange`)
- **Given** widget resolves to an active tenant → unchanged (issue session token).
- **Given** widget resolves to a non-active tenant → **`WidgetSessionError`** → route's
  uniform **403** (FR-012, FR-016). No session token minted.

### S4 — Chat auth (`deps.get_widget_session`)
- **Given** a valid token whose tenant is active → unchanged (yield claims).
- **Given** a valid token whose tenant is non-active → **generic widget 401** (FR-013,
  FR-016). Request refused before handler runs.

## Non-regression (active tenants)
- **S5**: For an active tenant, S1–S4 behave exactly as before this feature (FR-017).
