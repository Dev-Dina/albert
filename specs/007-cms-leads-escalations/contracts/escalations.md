# Contract: Escalations

Two surfaces: the **agent/tool write path** (persist on escalate) and the
**admin read path** (review).

## Write path — `escalate` tool (internal, not HTTP)

`escalate(*, tenant_id, conversation_id, reason, summary="", db)` — tenant_id and
conversation_id come from verified session context, **never client input**.

- Validates `reason` (1..1000, required) and `summary` (0..2000) via `EscalateArgs` (existing).
- Ensures the conversation row exists (existing behavior), sets `status='escalated'`.
- **NEW**: upsert one `escalations` row for the conversation:
  - none exists → insert `(tenant_id, conversation_id, reason, summary)`.
  - exists → update `reason`, `summary`, `updated_at`.
- Returns `{ "ticket_id": conversation_id, "status": "escalated" }` (unchanged shape).
- No DB session → logs warning, no persistence (existing degradation path), but
  this must not be the normal agent path.

## Admin read path — `/api/v1/admin/escalations`

Requires `AdminIdentityDep`. Tenant scope at app layer + RLS on `escalations`
and `conversations`.

### `GET /api/v1/admin/escalations`

List this tenant's escalated conversations (newest `updated_at` first).

- Query: `limit` (1..200, default 50), `offset` (≥0).
- 200 → `[EscalationResponse]`. Empty → `[]`.

### `GET /api/v1/admin/escalations/{conversation_id}`

- 200 → `EscalationResponse`. 404 if not this tenant's escalation.

### `EscalationResponse`

```json
{ "conversation_id": "uuid", "reason": "str", "summary": "str",
  "conversation_status": "escalated",
  "created_at": "iso8601", "updated_at": "iso8601" }
```

### Acceptance

- Escalate with reason+summary → row persisted; appears in admin list with both.
- Escalate with reason only → `summary=""` stored, no error (FR-033).
- Re-escalate same conversation → single row, fields updated (FR-034); no duplicate.
- Tenant B never sees Tenant A's escalations; `GET {conversation_id}` of A's
  conversation by B → 404.
