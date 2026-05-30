# Contract: Lead Lifecycle API

Extends existing `/api/v1/admin/leads` (router `admin_members_and_leads`).
All endpoints require `AdminIdentityDep`. Tenant scope at app layer + RLS on
`leads`.

## `GET /api/v1/admin/leads` — EXISTS (unchanged contract)

List tenant leads, optional `status`/`since`/`until`/`limit`/`offset` filters.

## `GET /api/v1/admin/leads/{lead_id}` — NEW

- 200 → `LeadResponse` (now includes `status_changed_at`).
- 404 if not this tenant's lead.

## `PATCH /api/v1/admin/leads/{lead_id}` — NEW

Change a lead's status along the allowed lifecycle.

- Body `LeadStatusUpdateRequest`: `{ "status": "new|contacted|qualified|won|lost" }`
- Behavior: load lead (tenant-scoped); validate target ∈ allowed transitions for
  current status; set `status` + `status_changed_at = now()`; persist.
- 200 → `LeadResponse`.
- Errors:
  - 422 — `status` not one of the five enum values.
  - 409 — disallowed transition (e.g. `won → contacted`, `qualified → new`),
    body unchanged, message names current and attempted status.
  - 404 — lead not found for this tenant.

### Allowed transitions

```text
new → contacted | lost
contacted → qualified | lost
qualified → won | lost
won, lost → (terminal — any change → 409)
```

### `LeadResponse` (extended)

```json
{ "id": "uuid", "name": "str", "contact": "str", "intent": "str",
  "status": "new", "status_changed_at": "iso8601|null",
  "created_at": "iso8601", "conversation_id": "uuid|null" }
```

### Tenant-isolation acceptance

- Tenant B `GET`/`PATCH` of Tenant A's `lead_id` → 404 (no existence disclosure).
- Status filter returns only the caller tenant's leads.
