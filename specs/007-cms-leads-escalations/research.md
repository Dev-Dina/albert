# Phase 0 Research: CMS Content, Lead Lifecycle & Escalation Capture

All four spec clarifications are resolved (see spec.md Clarifications). This
document records the technical decisions for grounding the design against the
**existing** codebase, so no `NEEDS CLARIFICATION` markers remain.

## R1. CMS storage — reuse existing `cms_pages` table

**Decision**: Reuse the existing `cms_pages` model/table (migration 0003). No new
content table. Fields already present: `id, tenant_id, title, slug, body,
is_published, created_at, updated_at`, with `UniqueConstraint(tenant_id, slug)`
and RLS forced on `app.current_tenant`.

**Rationale**: The table exists and is already RLS-protected and FK-linked to
tenants. The only gaps are the repo/service/API/UI and the ingestion read path.
Reusing it avoids a migration for content and keeps tenant isolation guarantees
already audited in 0003.

**Implications**:
- `slug` is required + unique per tenant. The create API will derive a slug from
  the title when not provided and enforce uniqueness (return 409 on conflict).
- `is_published` gates retrieval: only published pages are indexed/retrievable.
  v1 UI may default new pages to published=true (per spec "immediately
  publishable") but the column lets us honor a draft state later without schema
  change.

**Alternatives considered**: New `content_pages` table — rejected (duplicates an
existing, already-isolated table; needless migration churn).

## R2. Content → retrieval wiring — replace the `_fetch_content_pages` stub

**Decision**: Implement `cms_repo.get_pages(tenant_id, content_ids)` returning
`[{"content_id": <page_id>, "body": <body>}]` for **published** pages, and have
`ingestion._fetch_content_pages` call it (replacing the `return []` stub). The
existing `ingest_tenant_content` already chunks parent/child, embeds in batches,
records cost per tenant, and is idempotent per `content_id`
(`delete_chunks_for_content` then rewrite).

**Rationale**: The whole pipeline downstream of `_fetch_content_pages` is built
and tested; `content_id` already maps 1:1 to a page id. Minimal, surgical change.

**Implications**: Delete of a page must remove its chunks. Reuse
`ChunkRepo.delete_chunks_for_content(content_id, tenant_uuid)` on delete (a
"delete + no re-add" path), so retrievable knowledge converges.

**Alternatives considered**: A separate sync job — rejected; the existing
function is the contract the stub was a placeholder for.

## R3. Re-index timing — FastAPI BackgroundTasks under a tenant-scoped session

**Decision**: On create/update/delete, commit the content change first, then
schedule re-indexing via `fastapi.BackgroundTasks`. The background callable opens
its **own** tenant-scoped session (`get_tenant_db`-style: `set_config(
'app.current_tenant', tid, true)`) and calls `ingest_tenant_content(tenant_id,
content_ids=[page_id], db, embedder)` using `request.app.state.embedder`.

**Rationale**: Matches the clarified "background after save" decision; keeps the
admin save fast and within SC-001's ~1-minute convergence. BackgroundTasks needs
no broker (Redis/Celery) — appropriate for the current scale and avoids new
infra/deps (Principle: lean containers).

**Implications**:
- The request DB session and the background session are **separate** — never
  pass the request session into the background task (it is closed when the
  response returns). The background task sets its own RLS GUC.
- Failure handling: background indexing wraps errors, logs them (ids/status only,
  per Principle III), and leaves the saved content intact (edge case
  "Indexing failure after save"). Re-running ingestion for the page recovers it.

**Alternatives considered**: (a) Synchronous inline — rejected by clarification
(blocks admin on embedding latency). (b) Celery/RQ worker — rejected for v1
(new infra/deps, over-scale). (c) Manual re-index action — rejected by
clarification (staleness risk). A manual "Re-index" admin button MAY be added as
a recovery affordance but is not the primary path.

## R4. Lead lifecycle state machine

**Decision**: Define an authoritative transition map in the service layer:

```text
new       → {contacted, lost}
contacted → {qualified, lost}
qualified → {won, lost}
won       → {}        # terminal
lost      → {}        # terminal
```

Enforce in `admin_members_leads_service.update_lead_status`: load the lead
(tenant-scoped), reject (HTTP 409 / clear message) if the requested target is not
in the allowed set for the current status, else set `status` + `status_changed_at
= now()` and persist. A Pydantic `LeadStatus` enum validates the input value is
one of the five (reject unknown with 422).

**Rationale**: Centralizing the map in the service keeps transition logic
auditable in one place (Principle II) and testable in isolation. Storing the map
in code (not DB) is fine for a fixed v1 lifecycle.

**Implications**: Add `status_changed_at` column to `leads` (nullable, set on
first transition; backfill not required). Existing free-text statuses in seed
data should already be `"new"`; a data check is part of the migration notes.

**Alternatives considered**: DB-driven transition table — over-engineered for 5
fixed states. Allowing arbitrary status set — rejected by clarification.

## R5. Escalation persistence model (1:1)

**Decision**: New `escalations` table, one row per conversation
(`UNIQUE(conversation_id)`), columns: `id, tenant_id, conversation_id, reason,
summary, created_at, updated_at`. RLS forced on `app.current_tenant` (added to
the policy set, mirroring migration 0003). The `escalate` tool performs an
**upsert**: insert on first escalation, update `reason/summary/updated_at` on
re-escalation. Conversation status continues to be set to `escalated`.

**Rationale**: 1:1 matches the clarified decision and FR-034. A dedicated table
(vs. columns on `conversations`) keeps escalation context cohesive, lets the
admin escalations view query directly, and avoids widening the hot
`conversations` row. `tenant_id` denormalized onto the row so RLS applies
uniformly and the admin list filters without a join.

**Implications**:
- `escalate` tool gains a DB upsert path. It already receives verified
  `tenant_id`/`conversation_id` from session context (never client input) — keep
  that. It currently may create a `conversations` row if missing; the escalation
  upsert must occur after the conversation row exists (same transaction/flush).
- Admin escalations endpoint joins `escalations` → `conversations` (both
  tenant-scoped) to show status + reason + summary + timestamps.

**Alternatives considered**: (a) Reason/summary columns on `conversations` —
rejected (widens hot table, weaker cohesion, awkward 1:1 semantics). (b) 1:many
history table — rejected by clarification (v1 wants single coherent record).

## R6. AuthZ / tenant resolution — reuse `AdminIdentityDep`

**Decision**: All new admin endpoints depend on `AdminIdentityDep`
(`require_admin_identity`), which resolves `(user_id, tenant_id)` from the
verified `tenant_admin` membership/JWT and calls `set_tenant_context` to set the
RLS GUC on the request session. Tenant id is never read from body/query/path.

**Rationale**: This is the audited pattern already used by members/leads/widgets
routes; it gives application-layer scoping + RLS in one dependency (defense in
depth, Principle I).

**Implications**: Background re-index runs outside the request, so it cannot use
the request session's GUC — it sets its own (R3). Escalation persistence runs in
the widget/agent path (not admin); it uses the verified conversation-session
tenant context already threaded into the `escalate` tool.

**Alternatives considered**: `get_admin_tenant_id` header stub (used by
`/ingest`) — acceptable for the manual re-index trigger but not the primary auth
for new write endpoints; prefer the membership-verified `AdminIdentityDep`.

## R7. Testing strategy

**Decision**: For each gap add (a) repository/service unit tests, (b) API
integration tests, and (c) **cross-tenant red-team** tests asserting Tenant B
cannot read/modify/retrieve Tenant A's content/leads/escalations, plus an RLS
test that a wrong/empty `app.current_tenant` returns no rows (fail-closed).
Extend `backend/tests/redteam/cross_tenant_demo.py`.

**Rationale**: Principle IV + Principle I. Cross-tenant tests are the tripwire
for the project's one intolerable failure.

**Alternatives considered**: Happy-path-only tests — rejected (the cross-origin
bug history showed tests can pass while the real isolation property is untested).
