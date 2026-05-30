# Contract: Resolve / Reopen Escalation

Extends the feature-007 admin escalations surface (`contracts/escalations.md` in 007) with a
write path and an enriched response. Tenant scope at app layer (`AdminIdentityDep`) + RLS on
`escalations`.

## Enriched `EscalationResponse`

All three GET/PATCH responses now return:

```json
{
  "conversation_id": "uuid",
  "reason": "str",
  "summary": "str",
  "conversation_status": "escalated",
  "status": "open",            // NEW — "open" | "resolved"
  "resolved_at": null,          // NEW — iso8601 | null
  "resolved_by": null,          // NEW — uuid | null (acting admin user_id)
  "created_at": "iso8601",
  "updated_at": "iso8601"
}
```

## `GET /api/v1/admin/escalations`

List this tenant's escalations (newest `updated_at` first).

- Query: `status` (`open` | `resolved`, optional — omitted ⇒ all), `limit` (1..200, default
  50), `offset` (≥0).
- 200 → `[EscalationResponse]`. Empty → `[]`.
- Tenant scope is always applied first; `status` narrows within the tenant.

## `GET /api/v1/admin/escalations/{conversation_id}`

- 200 → `EscalationResponse`. 404 if not this tenant's escalation.

## `PATCH /api/v1/admin/escalations/{conversation_id}`  *(NEW)*

Resolve or reopen one escalation. Requires `AdminIdentityDep`.

### Request body

```json
{ "status": "resolved" }   // or { "status": "open" }
```

- `status` is required and MUST be `open` or `resolved`. Any other value ⇒ **422**
  (Pydantic enum), escalation unchanged.
- No `tenant_id` / `resolved_by` accepted from the client — tenant and acting user come from
  the verified membership.

### Responses

| Status | When |
|---|---|
| 200 → `EscalationResponse` | Resolved/reopened (or idempotent no-op); reflects new `status`, `resolved_at`, `resolved_by`. |
| 404 | No escalation for this `conversation_id` in the caller's tenant (includes cross-tenant attempts — no existence disclosure). |
| 422 | `status` missing or not in {`open`,`resolved`}. |
| 401 | Missing/invalid admin token (existing dependency behavior). |

### Behavior

- `status: "resolved"` → set `status='resolved'`, `resolved_at=now()`,
  `resolved_by=<acting admin user_id>`. Re-resolving an already-resolved escalation refreshes
  `resolved_at`/`resolved_by` (idempotent, FR-012).
- `status: "open"` → set `status='open'`, `resolved_at=NULL`, `resolved_by=NULL`.
- The linked conversation's own `status` is **never** changed (FR-005).
- `updated_at` is bumped on any successful write.

### Acceptance

- Resolve an open escalation → `status='resolved'`, `resolved_by`=caller, `resolved_at` set;
  persists across reload; conversation status unchanged.
- Reopen a resolved escalation → `status='open'`, `resolved_at`/`resolved_by` cleared.
- Re-resolve → single row, `resolved_at`/`resolved_by` refreshed; no duplicate.
- `status:"bogus"` → 422, row unchanged.
- Tenant B `PATCH` of Tenant A's conversation → 404, and Tenant A's escalation is unmodified.
- `GET ?status=open` excludes resolved; `?status=resolved` excludes open; omitted returns all.
