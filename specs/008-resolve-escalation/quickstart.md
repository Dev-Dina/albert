# Quickstart: Resolve Escalation

Local-dev steps to build, migrate, test, and live-verify this feature. Backend code is baked
into the image, so a plain restart will **not** pick up new code/migrations — rebuild.

## 0. Preconditions

- Stack up: `docker compose ps` (backend, admin, postgres healthy).
- Demo logins (password `admin123`): `admin-acme@example.com` (Tenant Acme),
  `admin-beta@example.com` (Tenant Beta). Admin UI: http://localhost:8501, backend:
  http://localhost:8000.
- There is at least one escalated conversation for Acme (the agent's `escalate` tool seeds an
  `escalations` row; if none, drive a chat to a human handoff or seed one).

## 1. Run tests on the host (no DB container needed)

In-memory SQLite, `asyncio_mode=auto`:

```powershell
uv run --directory backend pytest tests/test_escalation_lifecycle.py tests/test_escalation_resolve.py tests/redteam/test_cross_tenant_admin.py -q
uv run --directory backend pytest -q          # full backend suite (no regressions)
uv run --directory admin pytest -q            # admin page/nav tests
```

## 2. Apply the migration to the running stack

```powershell
docker compose build backend
docker compose up -d --force-recreate backend
docker compose exec backend alembic upgrade head    # applies 0016
docker compose exec backend alembic current         # expect 0016_escalation_status (head)
```

Verify columns + unchanged RLS on Postgres (port 5433):

```powershell
docker compose exec postgres psql -U albert -d albert -c "\d+ escalations"
# expect: status (not null, default 'open'), resolved_at, resolved_by
docker compose exec postgres psql -U albert -d albert -c "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname='escalations';"
# expect: t | t  (RLS still enabled + forced — unchanged)
```

## 3. Live verification — resolve persists (US1)

1. Sign in to the admin UI as `admin-acme@example.com`.
2. Open **Escalations**. Default filter shows **open** items.
3. Click **Resolve** on one. It disappears from the default (open) view.
4. Switch the filter to **resolved** → the item appears with its resolved-by/resolved-at.
5. Reload the page → the item is still resolved (persisted).
6. Switch filter to **resolved**, click **Reopen** → it returns to the open view, resolver
   fields cleared.

API spot-check:

```powershell
# (token = login as acme; conv = an escalated conversation id)
curl -X PATCH http://localhost:8000/api/v1/admin/escalations/$conv `
  -H "Authorization: Bearer $token" -H "Content-Type: application/json" `
  -d '{"status":"resolved"}'
# 200, body shows status=resolved, resolved_by=<acme admin>, resolved_at set
curl -X PATCH http://localhost:8000/api/v1/admin/escalations/$conv `
  -H "Authorization: Bearer $token" -d '{"status":"bogus"}'    # 422
```

## 4. Live verification — cross-tenant isolation (SC-004)

```powershell
# token_beta = login as admin-beta@example.com ; conv = ACME's escalated conversation id
curl -X PATCH http://localhost:8000/api/v1/admin/escalations/$conv `
  -H "Authorization: Bearer $token_beta" -H "Content-Type: application/json" `
  -d '{"status":"resolved"}'
# EXPECT 404 (no existence disclosure)
```

Then confirm in psql that Acme's escalation is **still `open`** (zero modification by Beta):

```powershell
docker compose exec postgres psql -U albert -d albert -c "SELECT status, resolved_by FROM escalations WHERE conversation_id='$conv';"
# expect: open | (null)
```

## 5. Decoupling check (SC-005)

After resolving in step 3, confirm the conversation's own status is unchanged:

```powershell
docker compose exec postgres psql -U albert -d albert -c "SELECT status FROM conversations WHERE id='$conv';"
# expect: escalated  (unchanged by resolve/reopen)
```
