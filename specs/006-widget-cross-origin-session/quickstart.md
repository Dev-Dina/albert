# Quickstart: Verify the Widget Cross-Origin Fix

Local verification that genuine cross-origin embeds work after the fix, that
the temporary `localhost:8000` hack is removed, and that isolation/anti-abuse
controls still hold. Run from the repo root with the Docker stack up
(`docker compose ps` → all healthy).

## 0. Recreate the backend after code changes

After editing backend source, rebuild + force-recreate (a plain restart keeps
stale env/code):

```powershell
docker compose up -d --build --force-recreate backend
```

## 1. Revert the temporary local hack (FR-013)

Remove the manually-added backend origin from Acme's allowlist. The seed already
provides the correct demo origin (`http://localhost:8080`), so nothing else is
needed.

```powershell
# Postgres is published on 5433 locally.
docker compose exec postgres psql -U albert_app -d albert -c `
  "DELETE FROM widget_allowed_origins WHERE origin = 'http://localhost:8000';"
```

Confirm Acme retains only the real demo origin:

```powershell
docker compose exec postgres psql -U albert_app -d albert -c `
  "SELECT origin FROM widget_allowed_origins ORDER BY origin;"
# Expect http://localhost:8080 (and any real customer origins) — NOT http://localhost:8000
```

## 2. Run the local demo (cross-origin embed, SC-001 / SC-005)

Serve the demo host page on its own origin (`http://localhost:8080`), which is
distinct from the backend origin (`http://localhost:8000`):

```powershell
# from scripts/demo_host
python -m http.server 8080
```

Open `http://localhost:8080/` and:

- Confirm the chat bubble renders bottom-right (the iframe was framed — proves
  `frame-ancestors` allows `:8080`).
- Open the widget, send a message, and confirm a reply arrives (proves the
  same-origin `/session` + `/chat` calls succeed **without** the `:8000` hack).
- DevTools → Network: `POST /api/v1/widget/session` returns **200** with the
  request `Origin: http://localhost:8000` (the iframe/backend origin). Before
  the fix this was **403**.

## 3. Confirm embedding is still blocked off-allowlist (SC-002)

Temporarily serve the demo from a non-allowlisted origin (e.g. another port not
in the allowlist) and reload: the chat bubble must NOT appear (the browser
refuses to frame `embed.html` because the parent origin is not in
`frame-ancestors`). The DevTools console shows a CSP frame-ancestors violation.

## 4. Confirm TTL-bounded revocation (FR-006 / FR-017)

1. With a chat session open and working from `:8080`, remove `http://localhost:8080`
   from Acme's allowlist (admin UI, or the SQL `DELETE` form above).
2. Reload the host page → the widget can no longer be framed (new embeds blocked
   immediately).
3. In the still-open prior tab, sending another message continues to work until
   the token expires (≤ 15 min) — this is the accepted TTL-bounded behavior, not
   a bug. (Re-add the origin afterward to restore the demo.)

## 5. Run the test suite (FR-012, SC-003, SC-004)

```powershell
docker compose exec backend pytest tests/test_widget_session.py `
  tests/test_widget_chat.py tests/test_widget_e2e_chat.py `
  tests/test_widget_origin_csp.py tests/test_widget_cors.py `
  tests/test_widget_rate_limit.py tests/test_widget_loader.py -q
```

Expected after the fix:

- Real-browser-origin session/chat tests **pass** (Origin == backend origin).
- Repurposed attacker-origin and origin-removal tests assert the **new**
  Approach-A behavior (success / TTL-bounded), not 403/401.
- `frame-ancestors`, anti-enumeration 403/401, rate-limit, and cross-tenant
  isolation tests **still pass**.

## 6. Tenant isolation spot check (SC-006)

```powershell
docker compose exec backend pytest tests/redteam/cross_tenant_demo.py -q
```

A token/identity for one tenant must never yield another tenant's data or a
reply attributed to a different tenant.
