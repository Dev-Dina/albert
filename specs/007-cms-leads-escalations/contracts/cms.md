# Contract: CMS Content API

Base: `/api/v1/admin/cms` — all endpoints require `AdminIdentityDep`
(verified `tenant_admin`; tenant id from membership/JWT, never from body/path).
Tenant scope enforced at app layer **and** by RLS on `cms_pages`.

## `GET /api/v1/admin/cms/pages`

List this tenant's content pages (newest first).

- Query: `limit` (1..200, default 50), `offset` (≥0), `published` (optional bool filter).
- 200 → `[CmsPageResponse]`. Empty tenant → `[]`.

## `POST /api/v1/admin/cms/pages`

Create a page.

- Body `CmsPageCreate`: `{ title: str (1..200), body: str (1..100000, non-empty after strip), slug?: str, is_published?: bool=true }`
- Behavior: derive `slug` from `title` if omitted; enforce `(tenant_id, slug)` uniqueness.
- On success: persist, **schedule background re-index** of this page, return 201 → `CmsPageResponse`.
- Errors: 422 empty/oversized body or invalid title; 409 slug conflict.

## `GET /api/v1/admin/cms/pages/{page_id}`

- 200 → `CmsPageResponse`. 404 if not found **for this tenant** (no existence disclosure cross-tenant).

## `PUT /api/v1/admin/cms/pages/{page_id}`

Update title/body/slug/is_published.

- Body `CmsPageUpdate` (same validation as create; all fields optional, at least one required).
- On success: persist, **schedule background re-index**, return 200 → `CmsPageResponse`.
- Errors: 404 (not this tenant), 409 slug conflict, 422 validation.

## `DELETE /api/v1/admin/cms/pages/{page_id}`

- On success: delete page, **schedule chunk removal** for `content_id == page_id` (no re-add), return 204.
- 404 if not this tenant's page.

## `POST /api/v1/admin/cms/pages/{page_id}/reindex` *(optional recovery affordance)*

- Re-run ingestion for one page synchronously-scheduled in background. 202 → `{ "scheduled": true }`. Recovery path for a failed background index.

### `CmsPageResponse`

```json
{ "id": "uuid", "title": "str", "slug": "str", "body": "str",
  "is_published": true, "created_at": "iso8601", "updated_at": "iso8601" }
```

### Tenant-isolation acceptance

- Tenant B `GET/PUT/DELETE` of Tenant A's `page_id` → 404 (never 200/403 that reveals existence).
- After create by A, A's agent retrieves the content; B's agent never does (cross-tenant retrieval test).
