# Quickstart — Widget, Admin & CI/CD (Owner D)

This is the 10-minute end-to-end path that proves SC-001: a tenant admin takes
an empty widget configuration to a working embed in under 10 minutes with no
engineer assistance.

Prerequisite: the foundation stack from earlier phases is up:

Recommended one-command path (migrations + manager + acme tenant admin + widget +
origin + Vault key + a second tenant):

```bash
cp .env.example .env
docker compose up -d
docker compose --profile bootstrap up bootstrap
```

Or the minimal login-only seed (platform manager + acme tenant admin), after a
build that bakes scripts into the image:

```bash
cp .env.example .env
docker compose up --build -d
docker compose exec -T backend alembic upgrade head
docker compose exec -T backend python scripts/seed_dev_user.py
```

Either path makes the admin dashboard login work:
`admin-acme@example.com` / `admin123` (tenant admin) — and
`manager@example.com` / `admin123` (platform manager).

## 1. Seed a demo tenant and tenant admin (one-time, by an engineer)

```bash
docker compose exec backend uv run python scripts/seed_demo_tenant.py \
  --slug acme \
  --admin-email admin-acme@example.com \
  --admin-password acme-dev-pass
```

This script (added by this feature) creates a `tenants` row, a `users` row
with `platform_role=tenant_manager`, a `tenant_memberships` row with
`role=tenant_admin`, and (via the rotate flow) the tenant's first signing key.

## 2. Log in to the admin app as the tenant admin

Open `http://localhost:8501` (the Streamlit `admin` service from `docker compose`).
Enter `admin-acme@example.com` / `acme-dev-pass`. The admin app calls
`POST /api/v1/auth/login`, stores the Bearer token in `st.session_state`, and
shows the **Widgets** page.

## 3. Create the widget, set theme + greeting

On the Widgets page:
- Click **New widget**.
- Name: `Acme demo`.
- Greeting: `Hi! I'm the Acme concierge. How can I help?`
- Theme: leave defaults.
- Save.

The backend generates a fresh `public_widget_id` (22-char base62).

## 4. Add the demo origin

Open **Allowed Origins**:
- Add `http://localhost:8080` (the static page you'll serve from in step 6).
- Save. The allowlist now contains exactly that one origin.

## 5. Copy the embed snippet

Open **Embed Snippet** for the new widget. Click **Copy**. The snippet looks like:

```html
<script src="http://localhost:8000/widget.js"
        data-widget-id="<22-char-id>" async></script>
```

## 6. Serve a static host page

In another shell:

```bash
mkdir /tmp/acme-host && cd /tmp/acme-host
cat > index.html <<'HTML'
<!doctype html>
<html><head><title>Acme</title></head>
<body>
  <h1>Acme demo</h1>
  <!-- paste the snippet from step 5 here -->
</body></html>
HTML
python -m http.server 8080
```

Open `http://localhost:8080/` in a browser. Within a second the chat iframe
loads, the widget calls `POST /api/v1/widget/session` from the browser, the
server checks the `Origin` header against the allowlist, issues a 15-minute
HS256-signed token, and the iframe renders the greeting from step 3.

## 7. Send a message

Type "hello" in the widget and press Send. The widget calls
`POST /api/v1/widget/chat` with `Authorization: Bearer <token>`. The response
appears in the chat surface.

## 8. Verify tenant safety (US2, 3 attacks)

Run the red-team script (added by this feature):

```bash
docker compose exec backend uv run python -m tests.redteam.cross_tenant_demo
```

It must report `3/3 attacks rejected`:
- Embed on `http://attacker.test/` is refused by both CSP and server-side origin check.
- `curl POST /api/v1/widget/chat` with a copied `widget_id` and a forged token is 401.
- `curl POST /api/v1/widget/chat` with a valid Tenant-A token and `tenant_id` of Tenant B in the body returns A's data only — never B's.

## 9. Rotate the signing key

On the **Signing Key** admin page, click **Rotate**. Confirm the modal. The
admin app calls `POST /api/v1/admin/signing-key/rotate`. The browser tab from
step 6 will, on its next chat send, get a 401, attempt a silent re-exchange
(which succeeds because origin and widget are unchanged), receive a new token
signed by the new key, and continue. Any *other* visitor's open token at that
moment would also be re-exchanged on the next send.

## 10. CI green-then-red demo

Push the branch. Watch the GitHub Actions run:
- Lint, type-check, image build, smoke, then four eval gates + redaction.
- All pass on placeholder fixtures.

Then in a throwaway commit, edit `evals/redteam_cross_tenant/fixtures/` to
remove an expected-fail row (simulating a regression that lets an attack
succeed). Push. CI must fail on the `redteam_cross_tenant` gate with a
message naming the gate and showing observed `< 1.00`. Revert and CI goes
green again.

---

**Expected wall-clock**: Steps 1–7 in under 10 minutes by a tenant admin with
no engineer (SC-001). Step 8 in under 30 seconds (SC-002, SC-003, SC-004).
Step 10 in under 10 minutes of CI wall clock (R10 in research.md).
