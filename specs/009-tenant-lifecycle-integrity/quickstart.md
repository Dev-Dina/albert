# Quickstart: verifying Tenant Lifecycle Integrity

## Prerequisites
- Stack up: `docker compose ps` (postgres, backend healthy).
- Backend code is baked into the image — after editing backend code:
  ```
  docker compose build backend && docker compose up -d --force-recreate backend
  ```
  No migration is needed for this feature.

## Run the tests

Host (SQLite, fast) — coverage guard + login/resolution lockout & non-regression:
```
uv run --directory backend pytest tests/test_erasure_coverage.py tests/test_tenant_status_enforcement.py -v
```

Postgres isolation evals — full erasure (escalations + memberships purged), live schema
coverage:
```
docker compose exec backend uv run pytest evals/isolation/test_erasure_total.py -v
```

## Live verification — erasure leaves nothing (disposable tenant)

1. Seed a disposable tenant with a conversation, an **escalation**, a **membership**, and
   a lead (see the verification approach used during analysis: insert under the
   `postgres` superuser, run `erase_tenant` under `SET ROLE albert_app`).
2. Confirm BEFORE: `escalations=1`, `tenant_memberships=1`, `leads=1`, `conversations=1`.
3. Run `erase_tenant`.
4. Confirm AFTER: **all four = 0** (previously `tenant_memberships` survived at 1).
5. Confirm the summary contains `postgres.escalations` and `postgres.tenant_memberships`
   with the right counts (previously both absent).
6. Confirm a second seeded tenant is fully intact (cross-tenant isolation).
7. Clean up the disposable tenant + users + membership.

## Live verification — status lockout

Using demo logins (password `admin123`): `admin-acme@example.com`. Erasure/suspend needs
a platform_manager token.

1. As a platform manager, suspend a tenant (`provisioning.suspend_tenant`) or set
   `tenants.status='suspended'` for a disposable tenant.
2. **Login**: that tenant's sole admin can no longer obtain a token (generic 401);
   an admin of a different active tenant is unaffected.
3. **Admin API**: a previously-issued admin token for the suspended tenant now gets 403
   on tenant-admin endpoints.
4. **Widget handshake**: `POST /api/v1/widget/session` for the suspended tenant's widget
   returns the uniform 403; no session token.
5. **Chat**: an already-issued widget token for the suspended tenant is refused (401) on
   the next chat request.
6. Reactivate the tenant (`reactivate_tenant`) and confirm all four work again.
7. Erase the disposable tenant and confirm login/widget/chat remain refused.

## Expected outcomes (success criteria)
- SC-001/002: every tenant-owned category (incl. escalations, memberships) → 0 rows and
  counted in the summary.
- SC-003: coverage guard fails loudly if a new `tenant_id` table is added uncovered.
- SC-004/005: non-active tenants refused on all four surfaces; active tenants unchanged;
  platform managers retain lifecycle access.
- SC-006: erasing one tenant leaves a second tenant fully intact.
