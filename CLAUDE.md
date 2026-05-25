# CLAUDE.md

Shared Claude Code instructions for Albert.

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan.
<!-- SPECKIT END -->

## Project

Albert is a multi-tenant AI SaaS concierge for businesses.

Any business can manage CMS content and embed an AI agent widget on its public site.

The highest priority is tenant isolation.

Tenant A must never access Tenant B data, vectors, leads, conversations, prompts, widget config, costs, or sessions.

## Team Rules

- Do not push directly to `main`.
- Work on a branch.
- Keep PRs small and focused.
- Do not hardcode secrets.
- Do not commit `.env`.
- Do not add real API keys, tokens, passwords, or private keys.
- Do not skip tests for changed behavior.
- Do not build ahead of the requested phase.

## Architecture Rules

- Keep logic separated:
  - routes
  - schemas
  - services
  - repositories
  - clients
  - config
- Use async patterns for API, database, and network work.
- Use centralized config.
- Use logging, not print.
- Do not log secrets, tokens, passwords, or raw sensitive data.
- Keep Docker containers lean.
- Do not add torch or transformers to serving containers unless explicitly approved.

## Tenant Safety Rules

- Never trust `tenant_id` from a visitor/client request body.
- Tenant identity must come from verified auth/session/widget token.
- Tenant-owned database rows must be scoped by tenant.
- RAG/vector retrieval must filter by tenant.
- Platform guardrails cannot be weakened by tenant config.

## Spec Kit Workflow

Use Spec Kit for feature work.

For simple safe features:

1. `/speckit.specify`
2. `/speckit.plan`
3. `/speckit.tasks`
4. `/speckit.implement`

For risky features:

1. `/speckit.specify`
2. `/speckit.clarify`
3. `/speckit.plan`
4. `/speckit.tasks`
5. `/speckit.analyze`
6. `/speckit.implement`

Risky features include:

- auth
- tenant isolation
- RLS
- widget token auth
- service-to-service auth
- guardrails
- erasure
- CI eval gates

## Protected Files

Warn before editing:

- `.env.example`
- `.gitignore`
- `.dockerignore`
- `docker-compose.yml`
- `Makefile`
- `.github/workflows/*`
- `backend/app/core/config.py`
- `backend/app/core/security.py`
- `backend/app/core/logging.py`
- `backend/app/db/session.py`
- auth files
- tenant isolation files
- database migrations
- platform prompts

## Git Rule

Claude should not run Git actions unless the user explicitly asks.

Prefer suggesting commands instead of running them.