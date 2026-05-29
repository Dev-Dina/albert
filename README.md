# Albert

Multi-tenant AI SaaS concierge for businesses.

Any business signs up, manages content in a CMS, and embeds an AI agent widget on its public site.

## Theme

Albert acts like a digital butler/concierge.

## What's implemented

Albert runs an end-to-end multi-tenant concierge stack. Pointers to each major area:

- **Tenant isolation** — Postgres RLS on the `app.current_tenant` session variable
  (FORCE RLS, `nullif(..., '')` fail-closed), repository-layer scoping, and a per-tenant
  pgvector filter. The runtime backend connects as a dedicated **non-superuser** role
  (`albert_app`) so RLS genuinely enforces. See [docs/DESIGN.md](docs/DESIGN.md) and
  [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md).
- **Widget auth** — signed, short-lived per-widget session tokens with a server-side
  origin re-check (CORS is not the boundary). See
  [specs/001-widget-auth-admin-cicd](specs/001-widget-auth-admin-cicd).
- **Guardrails** — a **NeMo Guardrails sidecar + deterministic platform-deny prefilter**,
  called over HTTP with a service credential. Deterministic platform denies run first;
  NeMo handles configurable tenant topical rails; redaction is separate. Platform rails
  cannot be weakened by tenant config.
- **Classifier-driven router** — most turns take a cheap workflow path
  (spam→drop, FAQ→RAG, lead→capture, escalate); the bounded agent handles only ambiguous
  turns. Routed-off-agent/cost report: `python -m evals.router_cost`.
- **Erasure** — total tenant deletion across Postgres, pgvector, MinIO, and Redis
  (traces carry no raw tenant data; ADR-013 in [docs/DECISIONS.md](docs/DECISIONS.md)).
- **Secrets** — runtime DB credentials and the service auth token are **Vault-backed when
  configured**, with a local-dev env fallback. See [docs/SECRETS.md](docs/SECRETS.md).
- **Evals + CI gates** — classifier, agent tool-selection, RAG (frozen lexical judge +
  hand-labelled agreement), cross-tenant red-team, redaction, isolation, plus a seeded
  Docker-compose smoke. Thresholds in [eval_thresholds.yaml](eval_thresholds.yaml);
  pipeline in [.github/workflows/ci.yml](.github/workflows/ci.yml). Overview:
  [docs/EVALS.md](docs/EVALS.md).

Operations (bring-up, migrations, seeding, tenant lifecycle, troubleshooting):
[docs/RUNBOOK.md](docs/RUNBOOK.md).

## Submission summary

```
Week 8 - Concierge (Albert)
Isolation: RLS (app.current_tenant, FORCE) + repo-layer + tenant-filtered pgvector
           runtime role albert_app (non-superuser, NOBYPASSRLS)
Roles: tenant_manager (platform) | tenant_admin | member - no content RLS bypass
Tenants: seeded on demand via scripts/seed_demo_tenant.py
Classifier task: intent routing (5 labels)  data: Bitext customer-support + UCI SMS Spam
Classifier - ML F1=0.9718 | DL(ONNX) F1=0.9834 | LLM F1=0.5036
           ships: Classical - fastest latency, lean serving (sklearn/joblib), SHA-pinned
Model served: sklearn/joblib  artifact SHA-256 pinned in modelserver/MODEL_CARD.md
Agent tools: rag_search | capture_lead | escalate   (bounded: max-iter + max-tokens)
Routing: workflow 80% | agent 20%   (cost saved: estimate, labelled in evals/router_cost)
RAG - chunking: hierarchical parent/child  improvement: Cohere rerank
      hit@5=1.00  faithfulness=0.974  answer_relevancy=0.940
Embedding model: text-embedding-004 (Gemini, hosted API)
Guardrails sidecar: NeMo Guardrails + deterministic platform-deny prefilter
                    platform denies (injection/jailbreak/cross-tenant/system-prompt/
                    tenant-override/tool-abuse/secret) run FIRST; NeMo runs the
                    configurable tenant topical rails (no LLM, no model download);
                    redaction separate + CI-gated
Widget auth: signed per-widget token + server-side origin check (CORS/CSP = depth)
Service-to-service auth: service token from Vault (env fallback for dev)
Redis short-term TTL: 1800s (30 min) - continuity vs anonymous-visitor privacy
Tracing backend: Jaeger (OpenTelemetry)
Widget bundle size: ~47 KB gzipped (148 KB raw); loader widget.js 977 B
LLM: Gemini - agent gemini-2.5-flash-lite; embeddings text-embedding-004
     (real GEMINI_API_KEY in Vault: secret/app/gemini_api_key; .env value is a dev placeholder)
Docs: docs/DESIGN.md, SPEC.md (+ specs/), docs/DECISIONS.md, docs/RUNBOOK.md,
      docs/EVALS.md, SECURITY.md
```

## Local Setup (Docker Compose)

Fresh-clone demo in three commands:

```bash
cp .env.example .env
docker compose up -d
docker compose --profile bootstrap up bootstrap   # migrate + seed demo data, then exits
```

The `bootstrap` step is idempotent (rerun-safe) and prints the demo URLs,
credentials, and the seeded widget id. Demo logins (**dev-only**, documented):

| Role | Email | Password |
|---|---|---|
| Platform manager (`tenant_manager`) | `admin@example.com` | `admin123` |
| Tenant admin for `acme` (`tenant_admin`) | `admin-acme@example.com` | `admin123` |

Admin UI: <http://localhost:8501> · Backend docs: <http://localhost:8000/docs> ·
Jaeger: <http://localhost:16686>. See [docs/RUNBOOK.md](docs/RUNBOOK.md) for details.

> Bootstrap is **dev/demo only** — weak passwords + dev-mode Vault. Never in production.

To run without seeding (services only):

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
- Jaeger tracing UI: <http://localhost:16686>

Notes:

- Vault runs in **local dev mode only** — see [SECURITY.md](SECURITY.md).
- `.env` is git-ignored; `.env.example` is tracked.

## Configuration

- Copy the example env file before running: `cp .env.example .env`.
- `.env` is git-ignored; `.env.example` is tracked (committed) and is the source of defaults.
- Backend config is centralized in `backend/app/core/config.py` (pydantic-settings); tests do
  not require a real `.env` (every setting has a default).
- Secret inventory and Vault/local fallback rules live in [docs/SECRETS.md](docs/SECRETS.md).

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

DB roles: the runtime backend connects as a dedicated **non-superuser** role
(`albert_app`, created by migration `0001`) so RLS is enforced at runtime —
`DATABASE_URL` points to it. Migrations need the admin/superuser login and run
DDL + `CREATE ROLE`, so set `MIGRATION_DATABASE_URL` to the `postgres` URL;
`alembic/env.py` prefers it and falls back to `DATABASE_URL` when unset.

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
| jaeger      | 16686 → 16686, 4317 → 4317, 4318 → 4318 | OpenTelemetry local tracing backend |

## Observability

Local distributed tracing uses OpenTelemetry with Jaeger all-in-one.

- Tracing backend: OpenTelemetry + Jaeger.
- UI: <http://localhost:16686>
- Config: `JAEGER_UI_BASE_URL=http://localhost:16686`,
  `JAEGER_QUERY_BASE_URL=http://localhost:16686`.
- Services traced: backend, modelserver, guardrails.
- Propagation: W3C trace context plus existing `X-Request-ID` correlation.
- Safety: do not trace raw user text, prompts, Authorization headers, cookies,
  service tokens, API keys, or raw PII/secrets.

Run `docker compose up --build`, send a request through the backend that calls
modelserver or guardrails, then open Jaeger and select the Albert services.

## Team Workflow

_Placeholder._

- Branch off `main`. No direct push.
- Small PRs. At least one reviewer.
- See [CONTRIBUTING.md](CONTRIBUTING.md) and [OWNERSHIP.md](OWNERSHIP.md).
