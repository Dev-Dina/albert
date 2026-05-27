# Data Model: Tenant Admin Management

No schema migration is required. This feature reads and writes existing tables only.

## Tables Used

### `tenants` (read-only in this feature)

| Column | Type | Used For |
|--------|------|----------|
| `id` | UUID | Path parameter lookup |
| `status` | VARCHAR | Gate check: must be `active` before adding admin |

### `users` (write on add, read on remove)

| Column | Type | Action |
|--------|------|--------|
| `id` | UUID PK | Created on add; referenced on remove |
| `email` | VARCHAR UNIQUE | Set on add |
| `hashed_password` | VARCHAR | Set on add (bcrypt) |
| `is_active` | BOOLEAN | Set to `true` on add |

### `tenant_memberships` (write on both add and remove)

| Column | Type | Action |
|--------|------|--------|
| `id` | UUID PK | Created on add; deleted on remove |
| `tenant_id` | UUID FK → tenants | Taken from URL path |
| `user_id` | UUID FK → users | New user on add; target user on remove |
| `role` | VARCHAR | Always `tenant_admin` for this feature |
| `created_at` | TIMESTAMPTZ | Set on add |

**Existing constraint**: `UNIQUE(tenant_id, user_id)` — prevents duplicate memberships.

### `audit_logs` (write on both add and remove)

| Column | Type | Value |
|--------|------|-------|
| `actor_user_id` | UUID FK → users | The tenant_manager making the request |
| `target_tenant_id` | UUID FK → tenants | The tenant being modified |
| `action` | VARCHAR | `tenant.admin.add` or `tenant.admin.remove` |
| `metadata` | JSONB | `{ affected_user_id: "...", email: "..." }` |

## State Transitions

```
Tenant status gate (add only):
  active   → allowed
  suspended → rejected (409)
  erased    → rejected (409)

Last-admin guard (remove only):
  membership_count > 1 → allowed
  membership_count == 1 → rejected (409)
```

## No New Entities

This feature introduces no new tables, columns, or indexes.
