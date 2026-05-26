# Albert

Multi-tenant AI SaaS concierge for businesses.

Any business signs up, manages content in a CMS, and embeds an AI agent widget on its public site.

## Theme

Albert acts like a digital butler/concierge.

## Phase 1 Goal

Get a runnable foundation first. Features come later.

This phase is only the repository foundation and folder skeleton. No app logic yet.

## Local Setup (Docker Compose)

Run the full local stack:

```bash
cp .env.example .env
docker compose up --build
```

Or use the Makefile:

```bash
make up      # build + start (detached)
make logs    # tail logs
make ps      # list services
make down    # stop
```

`.env` is local only and is never copied into images. Vault runs in **dev mode for
local use only** — do not use in production.

## Foundation verification

Verify the local foundation end to end:

```bash
cp .env.example .env
docker compose up --build
```

Then check:

- Backend health: <http://localhost:8000/health>
- Modelserver health: <http://localhost:8020/health>
- Guardrails health: <http://localhost:8010/health>
- MinIO console: <http://localhost:9001> (login `minioadmin` / `minioadmin`)
- Vault: <http://localhost:8200> (token `dev-root-token`)

Notes:

- Vault runs in **local dev mode only** — see [SECURITY.md](SECURITY.md).
- `.env` is git-ignored; `.env.example` is tracked.

## Configuration

- Copy the example env file before running: `cp .env.example .env`.
- `.env` is git-ignored; `.env.example` is tracked (committed) and is the source of defaults.
- Backend config is centralized in `backend/app/core/config.py` (pydantic-settings); tests do
  not require a real `.env` (every setting has a default).

## Backend Endpoints

- `GET /health` — fast liveness check returning `status`, `service`, `app`, `environment`.
  Does not check Vault, so it stays fast and stable.
- `GET /status/dependencies` — dependency reachability (Vault + database). Returns 200 even when
  a dependency is down: `{"vault": {"reachable": false}, "database": {"reachable": false}}`.

Vault dev server: `http://localhost:8200` (root token `dev-root-token`, **local only**).

## Database migrations

Platform tables (`tenants`, `users`, `tenant_memberships`, `audit_logs`) are managed with
Alembic. Apply the latest migrations:

```bash
cd backend
uv run alembic upgrade head
```

Inside Docker (recommended — resolves the `postgres` hostname on the compose network):

```bash
docker compose exec backend uv run alembic upgrade head
```

The local command requires `DATABASE_URL` to point at a database reachable from the host
(e.g. `postgresql+asyncpg://postgres:postgres@localhost:5433/albert`).

## Service Ports

| Service     | Host → Container       | Notes |
|-------------|------------------------|-------|
| backend     | 8000 → 8000            | `GET /health` |
| modelserver | 8020 → 8020            | `GET /health`, `POST /predict` |
| guardrails  | 8010 → 8010            | `GET /health`, `POST /check-input`, `POST /check-output` |
| postgres    | 5433 → 5432            | pgvector; db `albert`, user/pass `postgres` |
| redis       | 6379 → 6379            | redis:7 |
| minio       | 9000 → 9000, 9001 → 9001 | API / console; `minioadmin` / `minioadmin` |
| vault       | 8200 → 8200            | dev mode; root token `dev-root-token` (local only) |

## Team Workflow

_Placeholder._

- Branch off `main`. No direct push.
- Small PRs. At least one reviewer.
- See [CONTRIBUTING.md](CONTRIBUTING.md) and [OWNERSHIP.md](OWNERSHIP.md).
