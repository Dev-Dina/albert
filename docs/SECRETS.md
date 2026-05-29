# Albert Secret Inventory

This inventory separates secrets from non-secret configuration and records the
local-dev fallback path. Do not commit real secret values. Local `.env` is
git-ignored; `.env.example` contains placeholders only.

## Vault Strategy

Vault is the source of truth for runtime secrets. Local development may use env
fallbacks so services run without a real Vault setup.

Preferred flow:

1. Owner A/platform loads secrets from Vault.
2. Values are injected into process env or backend settings.
3. Backend, modelserver, and guardrails consume env/settings only.

Modelserver and guardrails do not call Vault directly (kept lean — no HTTP/Vault
client in the serving containers). They read `SERVICE_AUTH_TOKEN` from env and
fail closed when it is missing. The backend resolves the same token from Vault
when configured (see "Vault-backed service auth token"); the platform injects
that one secret into the sidecar env so the presented and expected tokens match.

### Vault-backed DB creds (runtime app role)

The runtime backend connects as the dedicated non-superuser role `albert_app`
(NOSUPERUSER, NOBYPASSRLS, not a table owner — so RLS is genuinely enforced).
Its password is a secret. Resolution (`backend/app/core/db_credentials.py`):

- `VAULT_DB_SECRET_PATH` unset → use `DATABASE_URL` from `.env` (dev fallback).
- `VAULT_DB_SECRET_PATH` set → resolve from Vault KV v2 at that path; if Vault is
  unreachable or the secret is missing, fall back to `DATABASE_URL` (dev never breaks).
- Migrations/admin always use `MIGRATION_DATABASE_URL` (`alembic/env.py`), never
  the runtime app credentials.

The Vault secret may carry either a full `url`/`database_url`, or
`username` + `password` (with optional `host`/`port`/`dbname`) spliced into the
`DATABASE_URL` template. Seed it (KV v2 mount `secret`, path `database/albert_app`):

```bash
# username/password form (spliced into the DATABASE_URL host/db):
vault kv put secret/database/albert_app username=albert_app password='<strong-secret>'
# or a full URL form:
vault kv put secret/database/albert_app \
  url='postgresql+asyncpg://albert_app:<strong-secret>@postgres:5432/albert'
```

Then set `VAULT_DB_SECRET_PATH=database/albert_app` in the backend env. The
`albert_app` role itself is created by migration `0001`; rotate its password in
Postgres and Vault together outside local dev.

### Vault-backed service auth token

The backend sends an `Authorization: Bearer <SERVICE_AUTH_TOKEN>` credential on
every modelserver/guardrails call. In real deployments that token should come
from Vault. Resolution (`backend/app/core/service_credentials.py`, mirrors the DB
creds pattern and reuses the same KV v2 read helper):

- `VAULT_SERVICE_AUTH_SECRET_PATH` unset → use `SERVICE_AUTH_TOKEN` from `.env`
  (dev fallback).
- `VAULT_SERVICE_AUTH_SECRET_PATH` set → resolve from Vault KV v2 at that path; if
  Vault is unreachable or the secret is missing, fall back to the env token (dev
  never breaks). In non-dev (`APP_ENV` not local/dev/test/ci) an empty token
  fails closed at startup.

The secret may expose `token`, `service_auth_token`, or `value`. Seed it
(KV v2 mount `secret`, path `service/albert`):

```bash
vault kv put secret/service/albert token='<strong-random-token>'
```

Then set `VAULT_SERVICE_AUTH_SECRET_PATH=service/albert` in the backend env. The
**sidecars stay env-based**: the platform injects this same secret value into the
modelserver/guardrails `SERVICE_AUTH_TOKEN` env (the sidecars never call Vault),
so the expected token matches the backend's Vault-resolved one.

Existing backend helper:

- `backend/app/core/secrets.py` reads `app/{name}` from Vault KV v2.
- `backend/app/clients/vault_client.py` uses `VAULT_ADDR`, `VAULT_TOKEN`, and
  `VAULT_MOUNT`.
- `get_secret_value("gemini_api_key", fallback=...)` supports Vault-first with
  local fallback for backend Gemini usage.

## Secret Config

| Name | Owner | Used by | Local fallback | Notes |
|---|---|---|---|---|
| `SERVICE_AUTH_TOKEN` | Owner C / Owner A injection | backend client, modelserver, guardrails | `.env` (dev) / Vault via `VAULT_SERVICE_AUTH_SECRET_PATH` (backend) | Internal bearer credential. Backend resolves from Vault when configured; sidecars receive the same secret via env injection. Never log or trace. |
| `GEMINI_API_KEY` | Owner C/B / Owner A injection | backend LLM/embeddings, Phase 4E LLM eval | `.env` | Primary LLM provider key. Phase 4E eval reads env only. |
| `GROQ_API_KEY` | Owner C / Owner A injection | Optional LLM baseline fallback | `.env` | Use only in a separate Groq baseline run; do not mix with Gemini metrics. |
| `JWT_SECRET` | Owner A | backend auth | `.env` | Signs platform/user JWTs. |
| Tenant widget signing keys | Owner A/D | backend widget session auth | Vault only preferred | Stored per tenant at `tenant/{tenant_id}/widget_signing_key`. |
| `DATABASE_URL` | Owner A | backend runtime (app role `albert_app`) | `.env` (dev) / Vault via `VAULT_DB_SECRET_PATH` | Non-superuser, NOBYPASSRLS. Vault-backed in real deploys; see "Vault-backed DB creds". |
| `MIGRATION_DATABASE_URL` | Owner A | Alembic migrations only (admin) | `.env` | Admin/superuser login for DDL + CREATE ROLE; runtime never uses it. |
| `POSTGRES_PASSWORD` | Owner A | local compose Postgres | compose env | Local dev only in compose. |
| `MINIO_ACCESS_KEY` | Owner A | backend/object storage | `.env` | Treat as secret credential. |
| `MINIO_SECRET_KEY` | Owner A | backend/object storage | `.env` | Treat as secret credential. |
| `VAULT_TOKEN` | Owner A | backend Vault client | `.env` | Local dev token only; never production. |

No `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `LANGSMITH_API_KEY`,
`DISCORD_WEBHOOK_URL`, SMTP secret, or Redis password is currently used by code.
No LangSmith dependency is present.

## Non-Secret Config

| Name | Purpose |
|---|---|
| `APP_ENV`, `APP_NAME`, `LOG_LEVEL` | App metadata/log level. |
| `BACKEND_PORT`, `ADMIN_PORT` | Local port hints. |
| `MODELSERVER_URL`, `GUARDRAILS_URL` | Internal service URLs. |
| `REDIS_URL` | Redis connection; secret only if password-bearing. |
| `MINIO_ENDPOINT`, `MINIO_BUCKET`, `MINIO_SECURE` | Object storage config. |
| `VAULT_ADDR`, `VAULT_MOUNT` | Vault location and KV mount. |
| `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` | Auth settings. |
| `GEMINI_MODEL`, `GEMINI_EMBEDDING_MODEL`, `GROQ_MODEL` | Provider model names. |
| `OTEL_ENABLED`, `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_ENVIRONMENT`, `OTEL_TRACES_EXPORTER` | OpenTelemetry config. |
| `JAEGER_UI_BASE_URL`, `JAEGER_QUERY_BASE_URL` | Local/dev Jaeger links/query base URL. |

Local Jaeger all-in-one does not need a key. Do not invent
`JAEGER_API_KEY`. If Albert later exports traces to a secured external OTLP
backend, Owner A should inject exporter credentials/headers through env/settings
and the tracing code must continue to avoid logging or tracing them.

## Jaeger Trace Visibility

Recommended UI/admin path for Week 8:

- Keep `X-Request-ID` visible in responses/logs.
- Use OpenTelemetry W3C `traceparent` for trace propagation.
- For admin demos, link operators to `JAEGER_UI_BASE_URL`.
- Do not expose the Jaeger query API to public visitors.

Preferred future implementation is an admin-only link or trace-id display. A
backend endpoint that calls `JAEGER_QUERY_BASE_URL` should only be added behind
existing admin/platform auth and should return sanitized summaries, not raw
trace payloads. Avoid iframe embedding unless the admin boundary and network
exposure are explicitly reviewed.

## LLM Baseline Provider Rule

Phase 4E uses Gemini as the primary zero-shot baseline provider. If Gemini is
unavailable, Groq may be run as a separate fallback baseline. Do not mix Gemini
and Groq predictions in one metrics file unless the file is explicitly marked as
mixed and excluded from final model comparison.
