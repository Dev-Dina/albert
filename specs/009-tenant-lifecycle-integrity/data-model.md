# Phase 1 Data Model: Tenant Lifecycle Integrity

No schema changes. This documents the entities the feature reasons about and the
canonical tenant-owned table set used by erasure and the coverage guard.

## Entities

### Tenant (`tenants`) — platform table, no RLS
- `id` (UUID, PK)
- `status` (string): `active` | `suspended` | `erased`. **Authority** for whether the
  tenant may be used. Erasure marks it `erased` (tombstone, not deleted).
- Other: `name`, `slug` (unique), timestamps.
- Lifecycle (existing, in `provisioning.py`): active ⇄ suspended (suspend/reactivate);
  active|suspended → erased (erase, terminal).

### Escalation (`escalations`) — tenant-owned, FORCE RLS
- `id` (UUID, PK), `tenant_id` (FK→tenants, CASCADE), `conversation_id` (FK→conversations,
  **ON DELETE CASCADE**), `status` (open|resolved), audit fields.
- **Erasure**: must be deleted **explicitly and before `conversations`** (see ordering).

### TenantMembership (`tenant_memberships`) — tenant-owned, **no RLS**
- `id` (UUID, PK), `tenant_id` (FK→tenants, CASCADE), `user_id` (FK→users, CASCADE),
  `role` (tenant_admin|member), unique(`tenant_id`,`user_id`).
- Neither FK cascade fires on erasure (tenant tombstoned, users kept) → must be deleted
  **explicitly** by `tenant_id`. Deleting the link never deletes the `users` row.

### Erasure audit summary (`dict[str,int]`)
- Per-category deleted-row counts. After this feature it MUST include
  `postgres.escalations` and `postgres.tenant_memberships`.

## Canonical tenant-owned table set (16, by `tenant_id` column)

Verified live (`information_schema.columns WHERE column_name='tenant_id'`):

```
child_chunks, cms_pages, content_chunks, conversations, cost_events, escalations,
leads, messages, parent_chunks, tenant_guardrail_configs, tenant_memberships,
widget_allowed_origins, widget_configs, widget_guardrail_configs,
widget_signing_key_versions, widgets
```

Erasure coverage set = `_TENANT_TABLES ∪ _OPTIONAL_LEGACY_TABLES`. The coverage guard
asserts: `{every table with a tenant_id column} ⊆ {erasure coverage set}`.

## Erasure delete ordering (post-change `_TENANT_TABLES`)

Children before parents; `escalations` before `conversations` for accurate counts (D1):

```
cost_events
leads
messages
escalations          # NEW — before conversations so the explicit delete count is real
conversations
child_chunks
parent_chunks
cms_pages
widget_configs
tenant_guardrail_configs
widget_allowed_origins
widget_signing_key_versions
widget_guardrail_configs
widgets
tenant_memberships   # NEW — no RLS, no FK ordering constraint; placed last
```

`_OPTIONAL_LEGACY_TABLES = [content_chunks]` (unchanged; existence-checked).

## State / status enforcement matrix

| Surface | Tenant identity source | Active? | Non-active result |
|---------|------------------------|---------|-------------------|
| `auth.login` | user's memberships (DB) | ≥1 active tenant OR platform manager → allow | no active tenant → generic 401 |
| `roles.resolve_current_user` | resolved membership.tenant_id | allow | 403 (same shape as "no role") |
| `widget_session_service.exchange` | trusted `widget_id` lookup → tenant_id | allow | uniform `WidgetSessionError` → 403 |
| `deps.get_widget_session` | verified token `tnt` claim | allow | generic widget 401 |

Platform managers (no tenant) bypass all tenant-status checks (FR-014).
