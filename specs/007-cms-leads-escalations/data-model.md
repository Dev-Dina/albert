# Phase 1 Data Model: CMS Content, Lead Lifecycle & Escalation Capture

All tenant-owned tables are protected by FORCE ROW LEVEL SECURITY with the
policy `tenant_id = nullif(current_setting('app.current_tenant', true), '')::uuid`
(pattern from migration 0003). Empty/unset GUC → no rows (fail closed).

## Entity: ContentPage (`cms_pages`) — EXISTS, reused

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants ON DELETE CASCADE | indexed; RLS key |
| `title` | str, NOT NULL | |
| `slug` | str, NOT NULL | unique per tenant `(tenant_id, slug)`; derived from title if omitted |
| `body` | text, NOT NULL default '' | 1..100,000 chars (non-empty after strip) — enforced at API |
| `is_published` | bool, NOT NULL default false | only published pages are indexed/retrievable |
| `created_at` | timestamptz | server default now() |
| `updated_at` | timestamptz | onupdate now() |

**No schema change.** Validation rules (API/service layer):
- Reject empty/whitespace `body` (422) and `body` > 100,000 chars (422).
- `slug` unique per tenant → 409 on conflict.

**Relationship to retrieval**: `cms_pages.id` is the `content_id` used by the
chunk pipeline (`parent_chunks.content_id`, child chunks via parent). Re-index
for a page is keyed on `content_id == page.id`.

**Lifecycle**: create → (edit)* → delete. Each create/edit/delete schedules a
background re-index; delete removes the page's chunks and does not re-add.

## Entity: Lead (`leads`) — EXISTS, extended

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | existing |
| `tenant_id` | UUID FK→tenants | existing; RLS key |
| `conversation_id` | UUID FK→conversations ON DELETE SET NULL, nullable | existing |
| `name` | str NOT NULL | existing |
| `contact` | str NOT NULL | existing |
| `intent` | text NOT NULL | existing |
| `status` | str NOT NULL default 'new' | constrained at app layer to the enum below |
| `created_at` | timestamptz | existing |
| **`status_changed_at`** | **timestamptz, nullable** | **NEW** — set to now() on each transition |

**LeadStatus enum** (validation values): `new`, `contacted`, `qualified`,
`won`, `lost`.

**State machine** (enforced in service; rejected transitions → 409):

```text
new       → contacted | lost
contacted → qualified | lost
qualified → won | lost
won       → (terminal)
lost      → (terminal)
```

Column stays `String` (no DB enum) to avoid a destructive type migration;
integrity is enforced in the service + covered by tests. Migration adds only
`status_changed_at`.

## Entity: Escalation (`escalations`) — NEW

| Field | Type | Notes |
|-------|------|-------|
| `id` | UUID PK | |
| `tenant_id` | UUID FK→tenants ON DELETE CASCADE, NOT NULL | indexed; RLS key |
| `conversation_id` | UUID FK→conversations ON DELETE CASCADE, NOT NULL | **UNIQUE** (1:1 per conversation) |
| `reason` | text, NOT NULL | 1..1000 chars (matches `EscalateArgs`) |
| `summary` | text, NOT NULL default '' | 0..2000 chars (empty allowed) |
| `created_at` | timestamptz | server default now() |
| `updated_at` | timestamptz | onupdate now() |

**Constraints**: `UNIQUE(conversation_id)` enforces 1:1. RLS forced on
`app.current_tenant` (added to the 0003-style policy set in the new migration).

**Upsert semantics**: first escalation inserts; re-escalation updates
`reason`, `summary`, `updated_at`. Conversation row must exist first (the
`escalate` tool already creates it if missing) — escalation insert references it.

**Relationship**: Escalation 1—1 Conversation; Conversation belongs to one
Tenant. Admin escalations view = `escalations ⋈ conversations` filtered by
tenant (both RLS-scoped).

## Migration: `0015_escalations_and_lead_status`

1. `CREATE TABLE escalations (...)` with FKs + `UNIQUE(conversation_id)`.
2. `ALTER TABLE escalations ENABLE/FORCE ROW LEVEL SECURITY` + tenant-isolation
   policy (USING + WITH CHECK), mirroring migration 0003.
3. `ALTER TABLE leads ADD COLUMN status_changed_at timestamptz NULL`.
4. `downgrade()` drops the column, policy, and table in reverse.

> Protected file class (migration). Flag in tasks/review; do not edit silently.
