# Security Notes

Albert's security posture. The highest priority is tenant isolation, and the core
controls below are **implemented**, not deferred:

- Postgres RLS on `app.current_tenant` (FORCE RLS, fail-closed) + repo-layer scoping +
  per-tenant vector filter; runtime connects as the non-superuser role `albert_app`.
- Signed short-lived widget session tokens with server-side origin re-check.
- NeMo Guardrails sidecar + deterministic platform-deny prefilter (platform rails run
  first and cannot be weakened by tenant config; NeMo runs the tenant topical rails),
  authenticated with a service credential.
- Total tenant erasure across Postgres, pgvector, MinIO, Redis.
- Vault-backed runtime DB credentials and service auth token (env fallback for local dev).

See [docs/DESIGN.md](docs/DESIGN.md), [docs/SECRETS.md](docs/SECRETS.md), and
[PROJECT_CONTEXT.md](PROJECT_CONTEXT.md). Vault itself still runs in **dev mode for local
use only** (below).

## Vault (local dev mode)

The `vault` service in `docker-compose.yml` runs in **dev mode**, for local development only:

- In-memory storage (all data is lost on restart).
- A fixed root token (`dev-root-token`) on an already-unsealed server.
- Plain HTTP (no TLS).

This is convenient for local work and is **never** suitable for production.

### Production Vault (future)

A production Vault deployment must, at minimum:

- Serve over **TLS**.
- Use **persistent, durable storage** (not in-memory dev mode).
- **Not** use a root token for normal operations.
- Define least-privilege **policies** scoped per service/tenant.
- Enable **audit logs**.
- Use a proper **auth method** (e.g. AppRole / OIDC), not static tokens.

## Secrets

- **No real secrets** may be committed to the repository.
- `.env` is git-ignored; only `.env.example` (placeholder values) is tracked.
- The values in `.env.example` are local-dev defaults, not real credentials.

## Service credentials

Service-to-service calls (backend → modelserver, backend → guardrails) are authenticated
with a bearer credential (`SERVICE_AUTH_TOKEN`); the sidecars validate it and **fail closed**
when it is missing. Both the runtime DB credentials and the service auth token are
**Vault-backed when configured** (`VAULT_DB_SECRET_PATH`, `VAULT_SERVICE_AUTH_SECRET_PATH`),
falling back to local `.env` values for development only. Resolution details and seeding
commands are in [docs/SECRETS.md](docs/SECRETS.md). No real secrets are committed; `.env`
is git-ignored and only `.env.example` (placeholders) is tracked.
