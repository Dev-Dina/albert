# Quickstart: CMS Content, Lead Lifecycle & Escalation Capture

Local validation flow once the feature is implemented. Stack must be up
(`docker compose ps` all healthy). Demo logins use password `admin123`:
`admin-acme@example.com`, `admin-beta@example.com`. Acme widget id
`SZKBnBgK8f9TR425FqFbkB`.

> Local-dev reminder: after editing `.env`, recreate the service —
> `docker compose up -d --force-recreate <svc>` (a plain restart keeps stale env).

## 0. Apply the migration

```powershell
docker compose exec backend alembic upgrade head   # applies 0015_escalations_and_lead_status
```

Verify RLS exists on the new table:

```powershell
docker compose exec postgres psql -U albert_app -d albert -c "\d+ escalations"
docker compose exec postgres psql -U albert_app -d albert -c "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='escalations';"
```

## 1. CMS — author content the agent answers from (Story 1)

```powershell
# Log in as Acme admin to get a token (existing auth flow), then:
# Create a page
curl -X POST http://localhost:8000/api/v1/admin/cms/pages -H "Authorization: Bearer <ACME_TOKEN>" -H "Content-Type: application/json" -d '{"title":"Refund policy","body":"We offer a 30-day refund on all plans."}'
# List
curl http://localhost:8000/api/v1/admin/cms/pages -H "Authorization: Bearer <ACME_TOKEN>"
```

- Within ~1 min, ask the Acme widget a related question ("what's your refund
  policy?") → answer reflects the authored content (SC-001).
- Edit the body → answer updates. Delete the page → content no longer retrieved (SC-002).

**Tenant isolation check**: with `<BETA_TOKEN>`, `GET /cms/pages/{acme_page_id}`
→ 404; Beta widget never surfaces Acme's refund text (SC-003).

## 2. Lead lifecycle (Story 2)

```powershell
# List leads, pick an id in status "new"
curl http://localhost:8000/api/v1/admin/leads -H "Authorization: Bearer <ACME_TOKEN>"
# Advance status (allowed)
curl -X PATCH http://localhost:8000/api/v1/admin/leads/<LEAD_ID> -H "Authorization: Bearer <ACME_TOKEN>" -H "Content-Type: application/json" -d '{"status":"contacted"}'
# Disallowed transition → 409
curl -X PATCH http://localhost:8000/api/v1/admin/leads/<LEAD_ID> -H "Authorization: Bearer <ACME_TOKEN>" -H "Content-Type: application/json" -d '{"status":"won"}'
```

- Allowed transition persists + `status_changed_at` set (SC-004).
- Disallowed transition (e.g. `contacted → won`) → 409, status unchanged.
- Beta admin PATCH of an Acme lead → 404.

## 3. Escalations (Story 3)

- Drive an Acme widget conversation to escalation (ask for a human).
- Confirm the escalation is stored with reason/summary:

```powershell
curl http://localhost:8000/api/v1/admin/escalations -H "Authorization: Bearer <ACME_TOKEN>"
curl http://localhost:8000/api/v1/admin/escalations/<CONVERSATION_ID> -H "Authorization: Bearer <ACME_TOKEN>"
```

- Reason+summary present (SC-005). Re-escalating the same conversation keeps a
  single row with updated fields (FR-034).
- Beta admin never sees Acme escalations (SC-003).

## 4. Admin UI (Streamlit, http://localhost:8501)

- Log in as `admin-acme@example.com`.
- **Content** page: create/edit/delete pages; see list.
- **Leads** page: open a lead, change status via the lifecycle control (only
  valid next states offered/accepted).
- **Escalations** page: list escalated conversations, read reason + summary.

## 5. Tests

```powershell
docker compose exec backend pytest backend/tests -q
docker compose exec admin pytest admin/tests -q   # or run in admin venv
```

Cross-tenant red-team additions in `backend/tests/redteam/cross_tenant_demo.py`
must pass: Tenant B cannot read/modify/retrieve Tenant A content, leads, or
escalations; empty/wrong `app.current_tenant` returns no rows.
