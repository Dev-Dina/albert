# Security Notes

Security posture of Albert's local development foundation. Intentionally minimal —
most controls arrive in later phases.

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

Service and integration credentials are intended to be sourced from **Vault** in later
phases (via the backend Vault client), not hardcoded or baked into images.
