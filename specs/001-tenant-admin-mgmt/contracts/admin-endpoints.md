# API Contracts: Tenant Admin Management

All endpoints require a valid `tenant_manager` bearer token.

---

## POST /tenants/{tenant_id}/admins

Add a new `tenant_admin` to an existing active tenant.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tenant_id` | UUID | Target tenant. Must exist and have status `active`. |

**Request Body**

```json
{
  "email": "admin@example.com",
  "password": "s3cur3pass"
}
```

| Field | Type | Validation |
|-------|------|------------|
| `email` | string (EmailStr) | Must be unique across the platform |
| `password` | string | Non-empty |

**Success Response — 201 Created**

```json
{
  "admin_user_id": "uuid",
  "email": "admin@example.com",
  "tenant_id": "uuid"
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid bearer token |
| 403 | Caller is not a `tenant_manager` |
| 404 | `tenant_id` not found |
| 409 | Email already registered OR user already admin of this tenant OR tenant not active |
| 422 | Invalid request body (bad email, missing fields) |

---

## DELETE /tenants/{tenant_id}/admins/{user_id}

Remove a `tenant_admin` from a tenant. Deletes the membership only — user account is preserved.

**Path Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `tenant_id` | UUID | Target tenant |
| `user_id` | UUID | User whose admin membership will be removed |

**Request Body**: None

**Success Response — 200 OK**

```json
{
  "tenant_id": "uuid",
  "removed_user_id": "uuid"
}
```

**Error Responses**

| Status | Condition |
|--------|-----------|
| 401 | Missing or invalid bearer token |
| 403 | Caller is not a `tenant_manager` |
| 404 | `tenant_id` not found OR `user_id` is not a `tenant_admin` of this tenant |
| 409 | `user_id` is the last admin — cannot remove |
| 422 | Malformed UUID in path |

---

## Audit Log Entries

Both endpoints write to `audit_logs`:

| Field | Add Admin | Remove Admin |
|-------|-----------|--------------|
| `action` | `tenant.admin.add` | `tenant.admin.remove` |
| `actor_user_id` | manager's user_id | manager's user_id |
| `target_tenant_id` | tenant_id from path | tenant_id from path |
| `metadata` | `{"affected_user_id": "...", "email": "..."}` | `{"affected_user_id": "..."}` |
