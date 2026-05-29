# Albert — Runbook

Operational guide for running, seeding, and maintaining Albert locally. For
architecture see [DESIGN.md](DESIGN.md); for secrets see [SECRETS.md](SECRETS.md); for
evals see [EVALS.md](EVALS.md).

## 0. Fresh-clone demo bootstrap (recommended)

One opt-in command brings the stack to a demo-ready state — migrations + platform
manager + demo tenants (`acme`, `beta`) + admins + widgets + allowed origins + Vault
signing keys. Idempotent.

```bash
cp .env.example .env
docker compose up -d
docker compose --profile bootstrap up bootstrap   # runs scripts/bootstrap_dev.py, then exits
```

It prints demo URLs + credentials and the seeded widget id. Demo logins (**dev-only**):
`admin@example.com / admin123` (platform `tenant_manager`) and
`admin-acme@example.com / admin123` (`tenant_admin` for `acme`). The `bootstrap`
service is profile-gated, so a plain `docker compose up -d` never runs it.

The steps below (§1–§3) are the manual equivalents the bootstrap automates.

## 1. Bring up the stack

```bash
cp .env.example .env          # local placeholders; .env is git-ignored
docker compose up --build     # or: make up
```

Health checks (all should return 200):

- Backend: <http://localhost:8000/health>
- Modelserver: <http://localhost:8020/health>
- Guardrails: <http://localhost:8010/health>
- MinIO console <http://localhost:9001> · Vault <http://localhost:8200> (token `dev-root-token`) · Jaeger <http://localhost:16686>

Ports and services are listed in [../README.md](../README.md#service-ports). Vault runs
in **dev mode (local only)** — never production.

## 2. Database roles & migrations

Two distinct DB principals (see [SECRETS.md](SECRETS.md)):

- **Runtime** `DATABASE_URL` → role `albert_app` (non-superuser, `NOBYPASSRLS`) so RLS
  genuinely enforces. This is what the backend connects as.
- **Admin** `MIGRATION_DATABASE_URL` → `postgres` superuser, used **only** for Alembic
  (DDL + `CREATE ROLE`). `alembic/env.py` prefers it when set.

Apply migrations:

```bash
# Inside Docker (resolves the `postgres` hostname):
docker compose exec backend uv run alembic upgrade head

# From the host (Postgres is published on localhost:5433):
cd backend
MIGRATION_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5433/albert \
  uv run alembic upgrade head
```

The runtime role and its grants (including `EXECUTE` on the widget-lookup function) are
created by the migrations; a fresh `upgrade head` from an empty DB applies `0001`→`0008`.

## 3. Seed a demo tenant

```bash
# Seeding creates a tenant + admin + widget + allowed origin + Vault signing key.
# It bootstraps tenant-scoped rows before any tenant context exists, so it runs under
# the ADMIN/migration URL (like migrations) — not the runtime app role.
docker compose exec -T backend sh -c \
  'DATABASE_URL="$MIGRATION_DATABASE_URL" python seed_demo_tenant.py --slug acme --origin http://localhost:8080'
```

(Script: [`scripts/seed_demo_tenant.py`](../scripts/seed_demo_tenant.py). It prints
`widget_id`, `allowed_origin`, and admin credentials. Idempotent per `--slug`.)

## 4. Smoke test

```bash
bash scripts/smoke_test.sh                  # default: seeded secured round-trip ON
SMOKE_SEEDED_CHAT=0 bash scripts/smoke_test.sh   # skip the seeded chat turn
```

Verifies: health of all three services; guardrails allow + block + legacy-route guard;
modelserver classifier + service-auth; widget `/session` origin gate; widget `/chat`
invalid-token 401; and (seeded) migrate → seed → real token exchange → one
guardrails-blocked chat turn (no LLM call). Tears the stack down (`-v`) on exit.

## 5. Production secrets (Vault)

Local dev uses `.env` fallbacks. In real deployments, set:

- `VAULT_DB_SECRET_PATH` → runtime DB credentials from Vault.
- `VAULT_SERVICE_AUTH_SECRET_PATH` → service auth token from Vault (sidecars receive the
  same value via env injection).
- **Gemini API key** → the real key is read from Vault at `secret/app/gemini_api_key`
  (the `.env` `GEMINI_API_KEY` is a dev placeholder only). The live agent/RAG model is
  `GEMINI_MODEL` (default `gemini-2.5-flash-lite`; `gemini-2.0-flash` is deprecated for
  new users). Without a real key, login/admin/blocked-chat work but a benign chat that
  reaches the agent returns a controlled **503** (no raw 500).

Seeding commands and resolution precedence are in [SECRETS.md](SECRETS.md).

## 6. Tenant lifecycle

- **Provisioning:** the Tenant Manager creates a tenant and invites its first
  tenant-admin; the platform operator never logs into a tenant to configure it.
- **Erasure:** `app/tenancy/erasure.py::erase_tenant` purges Postgres rows, pgvector
  embeddings, MinIO blobs, and Redis sessions, then marks the tenant `erased`. It is
  write/delete-only (the manager never reads content) and **audit-logged** with the
  actor id. Traces carry no raw tenant data by design (ADR-013).

## 7. Observability

- Distributed tracing: OpenTelemetry → Jaeger (<http://localhost:16686>), W3C
  `traceparent` + `X-Request-ID` correlation. Services traced: backend, modelserver,
  guardrails.
- Never trace raw user text, prompts, tokens, or secrets (redaction filter installed).

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `getaddrinfo failed` for host `postgres` | Running on the host, not in Docker. Use `localhost:5433` in `DATABASE_URL`/`MIGRATION_DATABASE_URL`. |
| Seed fails: `new row violates row-level security policy` | Seeding ran as `albert_app`. Run it under `MIGRATION_DATABASE_URL` (admin), as in §3. |
| `/api/v1/widget/session` returns 500 / 403 under the app role | Ensure migrations are at `head` (function `EXECUTE` grant + tenant-context fixes land in `0004`+code). |
| Guardrails calls 404 | Use the correct routes `/check-input` and `/check-output` (the backend client owns these names). |
| Tests: "Event loop is closed" | A module-level async engine reused across the TestClient per-request loop; patch the DB dependency in that test rather than touching a real DB. |
