# Albert

Multi-tenant AI SaaS concierge for businesses.

Any business signs up, manages content in a CMS, and embeds an AI agent widget on its public site.

## Theme

Named after Batman's butler. Albert acts like a digital butler/concierge.

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
