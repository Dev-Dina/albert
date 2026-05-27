# Implementation Plan: Widget Auth, Admin UX & CI/CD (Owner D)

**Branch**: `001-widget-auth-admin-cicd` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-widget-auth-admin-cicd/spec.md`

## Summary

Ship the public-facing surface of Albert: an embeddable chat widget (loader + iframe
bundle), a signed per-tenant token-exchange flow that derives `tenant_id` solely from
the token (never the request body), a per-tenant origin allowlist enforced server-side
plus CORS and `Content-Security-Policy: frame-ancestors` as defense-in-depth, a
Streamlit admin app for tenant self-service, and a GitHub Actions pipeline that gates
merges on lint, type-check, image build, a stack smoke test, and four eval gates whose
thresholds live in `eval_thresholds.yaml`.

The technical approach: extend the existing FastAPI backend with three new resource
groups (`widget`, `widget_allowed_origins`, `widget_session` token exchange) backed by
new tenant-scoped tables and Alembic migrations; store per-tenant signing keys in Vault
(KV v2) so tenant admins can rotate but never read them; back rate limiting with Redis
using two independent gates (per-IP and per-tenant) configured centrally; serve a tiny
versioned `widget.js` loader and an iframe bundle from the API service (no CDN in v1);
build a Streamlit admin app at `admin/` that consumes the existing platform auth; and
expand `.github/workflows/ci.yml` to run the gates in order, fail fast on the smoke
test, and surface observed-vs-threshold values on failure.

## Technical Context

**Language/Version**: Python 3.12 (backend, admin, eval scripts); TypeScript (widget bundle, compiled to a single ES module).

**Primary Dependencies**:
- Backend: FastAPI, SQLAlchemy 2.x (async), asyncpg, Alembic, python-jose (JWT), passlib[bcrypt], httpx, pydantic-settings, **new**: a `redis.asyncio` token-bucket built on top of Owner A's platform rate-limit primitive (Owner D adds the second dimension; does not fork a parallel system).
- Admin: **new** `streamlit`, `httpx` (call backend), `pydantic`.
- Widget bundle: **React 18** + TypeScript, compiled with `esbuild` (single ESM module). React was selected per Owner D's scope sheet. Bundle target: ≤ 110 KB minified (React + ReactDOM runtime + chat UI); loader stays ≤ 4 KB.
- CI: GitHub Actions, `docker compose`, `uv`, `ruff`, `mypy` (or `pyright`), `pytest`, `vitest` (widget unit tests).

**Storage**:
- PostgreSQL 16 (pgvector image) — existing. Add `widgets`, `widget_allowed_origins`, `widget_guardrail_configs`, `widget_signing_key_versions` tables (tenant-scoped). The actual key material lives in Vault, not Postgres.
- Vault (KV v2, dev mode locally) — already wired via `app/clients/vault_client.py`. Per-tenant signing keys stored at `secret/data/tenant/{tenant_id}/widget_signing_key`.
- Redis — used for rate-limit counters (token-bucket per IP and per tenant); already in compose.
- MinIO is **not** used by this feature in v1 (widget bundle is served directly by the API service).

**Testing**:
- `pytest` for backend unit/integration (existing).
- `pytest` + `httpx` for cross-tenant red-team and API integration tests.
- `playwright` is **not** introduced (out of scope) — widget UX is validated via the iframe HTML contract test and a manual quickstart, not an end-to-end browser harness.
- Streamlit admin: light pytest coverage of the underlying service functions (no Streamlit UI driver).
- CI evals: small `pytest`-style scripts under `evals/` that load fixtures and assert against `eval_thresholds.yaml`.

**Target Platform**:
- Backend, admin, modelserver, guardrails: Linux containers via `docker-compose`, dev on Windows/macOS/Linux host.
- Widget bundle: evergreen browsers (last 2 versions of Chromium, Firefox, Safari); ES2020; no IE support.

**Project Type**: Web application — multi-service: `backend/` (FastAPI), `admin/` (Streamlit), `widget/` (TypeScript bundle), `modelserver/` (existing), `guardrails/` (existing), CI scripts under `evals/` and `scripts/`.

**Performance Goals**:
- Token-exchange p95 < 100 ms server-side (excludes network).
- Chat request p95 added overhead from session-token verification: < 5 ms (HMAC verify + RLS context setter only).
- Rate limiter overhead: < 2 ms per call (Redis pipeline).
- `widget.js` loader: < 4 KB minified; widget bundle (React + ReactDOM + chat UI): ≤ 110 KB minified before gzip, ≤ 45 KB gzipped.

**Constraints**:
- Tenant isolation is non-negotiable (Constitution Principle I). `tenant_id` MUST be derived from the verified session token and **never** from the request body.
- Per-tenant signing keys: leak/rotation contained to a single tenant.
- Allowlist matching: exact origin (scheme + host + port). No wildcards in v1.
- Token validity: **15 minutes** with silent re-exchange. Clock skew tolerance: ±60 seconds.
- Rate limits: per-tenant **120 token exchanges / minute**, per-IP **30 token exchanges / minute**; both checked on every call. All values live in centralized config and are env-overridable.
- Secrets are never logged (Constitution Principle III). Tenant signing keys are **not** readable through any tenant-scoped API.
- Lean serving containers: do **not** add `torch`, `transformers`, or `playwright` to backend/admin/widget images.
- CI gate failures must not be silently retried.

**Scale/Scope**:
- Tens of tenants for v1; tens of widgets per tenant maximum; hundreds of concurrent visitors per tenant peak.
- Eval datasets are small enough to run in a single GitHub Actions job (< 5 minutes wall clock total for the four eval gates combined). Real datasets are owned by Owners A/B/C; this plan ships fixture-shaped placeholders and the gate plumbing.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Tenant Isolation Is Absolute | **PASS** | `tenant_id` is derived from the verified session token; the request body `tenant_id` is explicitly ignored. Widgets and allowed-origins rows are tenant-scoped with FK + RLS. Signing keys are per-tenant. Cross-tenant red-team is a CI gate with 100% pass bar (FR-026, SC-002). |
| II. Layered Architecture & Async Discipline | **PASS** | New code is split into `routes/`, `schemas/`, `services/`, `repositories/`, `clients/`, `config`. All DB/Vault/Redis I/O is async (asyncpg, httpx, redis.asyncio). Rate-limit values live in `app/core/config.py` (existing centralized config), not in route handlers. Logging via stdlib `logging`, never `print`. |
| III. Security & Secrets Hygiene | **PASS** | Per-tenant signing keys live in Vault, never in `.env.example`. Tokens, key material, rate-limit-trip details are logged with structured fields only — never the raw key, never the raw token. No new entries in `.env.example` carry real secrets; only defaults (`dev-*`) and tunable knobs. |
| IV. Test Integrity for Changed Behavior | **PASS** | Every new behavior (token exchange success/failure, origin check, body-`tenant_id` ignore, key rotation invalidates tokens, rate-limit dual-gate, CSP header derivation, admin guardrail-floor enforcement) is covered by a test before it is marked done. Cross-tenant red-team set is itself a CI gate. |
| V. Spec-Driven, Phased Delivery | **PASS** | Running the risky-feature flow: specify → clarify → plan → tasks → analyze → implement. This file is the planning phase; no implementation lands until tasks.md and analyze succeed. PRs will be split per user story (US1, US2, US3, US4) to keep them small and reviewable. |

**Operational constraints check**:
- Serving containers stay lean: no `torch`/`transformers`/`playwright` added to backend or admin images.
- Protected files touched: **WARN** — this plan will require edits to `.env.example` (new tunables — defaults only), `docker-compose.yml` (add `admin` service exposing Streamlit on 8501), `Makefile` (new `make admin`, `make eval`, `make smoke` targets), `.github/workflows/ci.yml` (entire pipeline rewrite), `backend/app/core/config.py` (new tunables only — no behavior change to existing keys), and migrations (added, not edited).
- Each protected-file change will be called out in the corresponding PR description and reviewed explicitly per Constitution + CLAUDE.md.

**Complexity Tracking**: No violations to justify. Two design choices that *look* like complexity but aren't:
- Storing signing keys in Vault rather than Postgres: required by FR-010b (admins must not be able to read the key); not a complexity overhead, a security control.
- Two independent rate-limit gates: required by FR-015a (neither dimension alone can exhaust the other); the alternative (single gate) would violate the spec.

## Project Structure

### Documentation (this feature)

```text
specs/001-widget-auth-admin-cicd/
├── plan.md              # This file (/speckit-plan output)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (OpenAPI fragments + JSON schemas)
│   ├── widget-session.openapi.yaml
│   ├── widget-chat.openapi.yaml
│   ├── widget-admin.openapi.yaml
│   ├── widget-loader.contract.md
│   └── ci-gate.contract.md
├── spec.md
├── checklists/
└── tasks.md             # Phase 2 output (/speckit-tasks command — NOT created here)
```

### Source Code (repository root)

```text
backend/
├── alembic/
│   └── versions/
│       ├── 0001_initial_platform_tables.py       # existing
│       ├── 0002_add_user_platform_role.py        # existing
│       └── 0003_widget_tables.py                 # NEW: widgets, allowed_origins,
│                                                 # guardrail_configs, signing_key_versions
├── app/
│   ├── api/
│   │   ├── deps.py                               # existing — add get_widget_session()
│   │   └── routes/
│   │       ├── auth.py                           # existing
│   │       ├── health.py                         # existing
│   │       ├── status.py                         # existing
│   │       ├── widget_loader.py                  # NEW: /widget.js, /widget/bundle.js
│   │       ├── widget_session.py                 # NEW: /api/v1/widget/session
│   │       ├── widget_chat.py                    # NEW: /api/v1/widget/chat
│   │       └── admin_widgets.py                  # NEW: /api/v1/admin/widgets/* (tenant-admin)
│   ├── clients/
│   │   ├── vault_client.py                       # existing — extend with widget_signing_key
│   │   └── redis_client.py                       # NEW: async Redis connection pool
│   ├── core/
│   │   ├── config.py                             # existing — add widget + rate-limit knobs
│   │   ├── security.py                           # existing — add widget-token mint/verify
│   │   ├── rate_limit.py                         # NEW: two-dimensional token bucket
│   │   └── tenant_context.py                     # NEW: set RLS / async-local tenant id
│   ├── db/
│   │   ├── models/
│   │   │   ├── widget.py                         # NEW
│   │   │   ├── widget_allowed_origin.py          # NEW
│   │   │   ├── widget_guardrail_config.py       # NEW
│   │   │   └── widget_signing_key_version.py    # NEW (metadata only; material in Vault)
│   │   └── session.py                            # existing
│   ├── repositories/
│   │   ├── widget_repo.py                        # NEW
│   │   ├── allowed_origin_repo.py                # NEW
│   │   └── guardrail_config_repo.py              # NEW
│   ├── schemas/
│   │   ├── widget.py                             # NEW
│   │   ├── widget_session.py                     # NEW
│   │   └── admin_widget.py                       # NEW
│   ├── services/
│   │   ├── widget_session_service.py             # NEW: orchestrates origin check,
│   │   │                                          #      rate-limit, key fetch, mint/verify
│   │   ├── widget_admin_service.py               # NEW: admin-side CRUD + guardrail floor
│   │   └── guardrail_floor.py                    # NEW: enforces platform-floor
│   └── main.py                                   # existing — register new routers
└── tests/
    ├── test_widget_session.py                    # NEW: success + 401/403/429 paths
    ├── test_widget_chat.py                       # NEW: body-tenant-id ignored, RLS set
    ├── test_widget_admin.py                      # NEW: tenant-admin scoping, floor refusal
    ├── test_widget_origin_csp.py                 # NEW: per-tenant CSP/CORS derivation
    ├── test_widget_rate_limit.py                 # NEW: per-IP + per-tenant dual-gate
    ├── test_widget_loader.py                     # NEW: /widget.js + fail-closed on bad id
    └── test_widget_key_rotation.py               # NEW: rotation invalidates outstanding tokens

admin/                                            # NEW Streamlit app
├── Dockerfile
├── pyproject.toml
├── app/
│   ├── main.py                                   # Streamlit entry: st.set_page_config + nav
│   ├── pages/
│   │   ├── 1_Widgets.py                          # list + edit (theme/greeting)
│   │   ├── 2_Allowed_Origins.py                  # list + add/remove
│   │   ├── 3_Guardrails.py                       # tenant guardrail config (floor-enforced)
│   │   ├── 4_Embed_Snippet.py                    # copy-ready snippet
│   │   └── 5_Signing_Key.py                      # rotate-only action with confirm modal
│   ├── clients/
│   │   └── backend_client.py                     # httpx wrapper, uses session JWT
│   └── lib/
│       └── auth.py                               # login form, token in session_state
└── tests/
    └── test_backend_client.py

widget/                                           # NEW — React 18 + TS, esbuild
├── package.json                                  # react, react-dom, typescript, esbuild, vitest
├── tsconfig.json
├── esbuild.config.mjs                            # two entry points: loader, bundle
├── src/
│   ├── loader.ts                                 # compiled to widget.js (no React import)
│   ├── iframe-bootstrap.tsx                      # runs inside the iframe; mounts <App/>
│   ├── App.tsx                                   # React root: chat surface
│   ├── api.ts                                    # token exchange + chat fetch + retry
│   ├── session.ts                                # silent re-exchange, expiry detection
│   └── ui/
│       ├── Chat.tsx
│       ├── MessageList.tsx
│       ├── Composer.tsx
│       └── styles.css
└── tests/
    ├── api.test.ts                               # vitest, hits a mocked /widget/session
    └── session.test.ts                           # silent re-exchange + 401-retry behavior

evals/                                            # NEW — CI eval harnesses
├── classifier/
│   ├── fixtures/                                 # placeholder until Owner A's set lands
│   └── run.py                                    # reads eval_thresholds.yaml.classifier
├── tool_selection/
│   └── run.py                                    # reads .agent_tool_selection
├── rag/
│   └── run.py                                    # reads .rag
├── redteam_cross_tenant/
│   ├── fixtures/
│   └── run.py                                    # reads .redteam — 100% required
├── redaction/
│   ├── fixtures/                                 # planted fake secrets only
│   └── run.py                                    # reads .redaction — 100% required
└── common/
    └── thresholds.py                             # loads eval_thresholds.yaml

scripts/                                          # existing (empty)
├── smoke_test.sh                                 # NEW: docker compose up + curl /health
└── seed_demo_tenant.py                           # NEW: tenant + widget + allowed_origin for demo

eval_thresholds.yaml                              # existing — tighten placeholders + add
                                                  # ci_time_budget / smoke section
.github/workflows/
└── ci.yml                                        # EXPANDED: lint → typecheck → build → smoke
                                                  # → 4 eval gates

docker-compose.yml                                # ADD: admin service on :8501
.env.example                                      # ADD: WIDGET_* + RATE_LIMIT_* tunables
Makefile                                          # ADD: admin, eval, smoke, widget-build targets
```

**Structure Decision**: Multi-service web app. Each new surface is its own directory at the repo root (`admin/`, `widget/`, `evals/`) to mirror the existing per-service pattern (`backend/`, `modelserver/`, `guardrails/`), keep Docker contexts lean, and let each owner work independently. The backend gets new packages under existing layers (`routes`, `services`, `repositories`, `schemas`, `clients`, `core`) per Constitution Principle II — no new top-level Python package inside `backend/app/`.

## Phase 0 — Research

See [research.md](./research.md). All NEEDS CLARIFICATION items resolved:
- Token TTL: **15 minutes** (clarification session 2026-05-26 + research on visitor-friction trade-offs).
- Rate-limit algorithm: **token bucket in Redis** via `redis.asyncio` pipeline (60 LOC, no extra dep beyond `redis`).
- Widget bundle build: **esbuild** (single-file ESM, no React).
- CSP / `frame-ancestors`: emitted dynamically per widget from the resolved `Allowed Origin` list — researched cross-browser behavior (Chromium, Firefox, Safari) and confirmed `frame-ancestors` is the only effective control vs. iframe-in-iframe wrapping.
- Eval gate fixture strategy: ship placeholders + clearly-marked TODO stubs; gates are wired and enforce thresholds even on placeholders, so Owner A/B/C drop-in is mechanical.
- Streamlit auth: re-use existing JWT login via `/api/v1/auth/login`; store token in `st.session_state`; never persist.
- Admin guardrail floor: per-platform YAML at `guardrails/app/platform_floor.yaml` (NEW, owned here for v1 unless Owner C claims it).

## Phase 1 — Design & Contracts

Artifacts produced:
- [data-model.md](./data-model.md) — entities, fields, relationships, RLS scope.
- [contracts/](./contracts/) — OpenAPI fragments per route group + a markdown contract for `widget.js` (it has no JSON schema) + a markdown contract for the CI gate output format.
- [quickstart.md](./quickstart.md) — 10-minute end-to-end demo path (matches SC-001).
- Agent context update: `CLAUDE.md` SPECKIT block points to this plan.

**Post-design Constitution re-check**: PASS. No new principle violations introduced by the contracts (each route is tenant-token-derived; admin routes require tenant-admin role; widget routes never accept body `tenant_id`; rate-limit headers documented; CSP derived from allowlist).

## Phase 2+ — Stop Point

This command (`/speckit-plan`) stops here. Phase 2 (tasks.md) is produced by
`/speckit-tasks`; analysis by `/speckit-analyze`; implementation by `/speckit-implement`.
No source code is changed by this command.

## Complexity Tracking

No Constitution violations to justify.

## Cross-owner handoffs

This feature (Owner D) sits on top of work owned by Owners A/B/C. Boundaries:

| Surface | Owner D builds | Owner D consumes (does NOT re-implement) |
|---|---|---|
| **Auth / roles** | Admin pages gate on `tenant_membership.role = "tenant_admin"`. | Owner A's `fastapi-users` setup, three-role model (Tenant Manager / tenant-admin / member), login JWT, and the `get_current_user` dep. |
| **Tenant context / RLS** | New tables (`widgets`, `widget_allowed_origins`, `widget_guardrail_configs`, `widget_signing_key_versions`) get RLS policies in this feature's migration, using Owner A's pattern. | Owner A's per-request `app.tenant_id` session-variable dependency and the repository-layer scoping helper. If A's primitive isn't merged when this feature lands, the migration ships behind a flag and the RLS test fails CI until the primitive is in place. |
| **Rate limiting** | The two-dimensional gate (per-IP + per-tenant) on `POST /api/v1/widget/session` specifically. | Owner A's platform rate-limit primitive (Redis token bucket). Owner D adds the per-IP dimension; per-tenant dimension reuses Owner A's bucket. No parallel rate-limit system. |
| **Service-to-service auth** | Nothing new; widget chat calls happen inside the API process. | Owner C's S2S auth (token / mTLS from Vault) when the API later forwards to modelserver / guardrails. |
| **Classifier eval gate (FR-023)** | The gate runner, threshold parsing, CI step, failure summary. | Owner C's classifier test set + model card. |
| **Agent tool-selection gate (FR-024)** | Gate runner + CI step. | Owner B's golden set + agent. |
| **RAG gate (FR-025)** | Gate runner + CI step. | Owner B's RAG golden set. |
| **Cross-tenant red-team gate (FR-026)** | Gate runner + CI step + 100%-pass enforcement. | Owner C's red-team set. |
| **Redaction gate (FR-027)** | Gate runner + CI step. | Owner C's redaction layer + planted-secret fixtures. |
| **Smoke test (FR-028)** | Entire script + CI step. | The compose stack already shipped in earlier phases. |
| **Platform guardrail floor** | `services/guardrail_floor.py` (validation) + admin-side refusal UX. | Owner C may take ownership of `guardrails/app/platform_floor.yaml` later; Owner D ships it for v1 only if C hasn't. |

Owner D ships **placeholder fixtures** for the four agent/safety datasets so CI is
exercised end-to-end on day 1; drop-in replacement by the owning author is
mechanical (same file paths, same threshold keys).

## Open Risks (to be carried into tasks.md)

- **Tenant-admin auth source (Owner A dependency)**: per-tenant admin auth (the `tenant_admin` role + the `current_tenant_id` resolver) is owned by Owner A. If it is not in place by the time admin pages land, US3 must temporarily gate on `platform_role = "tenant_manager"` plus an explicit `tenant_id` query param — and that gating must be removed before US3 is merged. Track as task dependency.
- **RLS primitive (Owner A dependency)**: the per-request `app.tenant_id` session-variable dependency and repository scoping helper are Owner A's. This feature's migration adds RLS policies that USE that variable; if A's primitive isn't merged, those policies will silently return zero rows (intentional fail-closed) and the integration tests will fail CI until A lands. Do not paper over.
- **Rate-limit primitive (Owner A dependency)**: the per-tenant token-bucket helper is Owner A's; Owner D's gate composes it with a per-IP bucket. If A's helper hasn't landed, build the per-tenant bucket here under `app/core/rate_limit.py` with an explicit "TODO: extract once Owner A's primitive merges" marker so it is mechanically lifted later.
- **React bundle size**: the 110 KB / 45 KB-gzipped target is comfortable but not free. tasks.md should include a CI check that fails the build if `widget/dist/bundle-*.js` exceeds the budget after minification.
- **RLS policy migration**: tenant-owned tables added here (`widgets`, `widget_allowed_origins`, `widget_guardrail_configs`) require RLS policies in the same Alembic revision; tasks.md must include a RLS test that proves cross-tenant SELECT returns zero rows.
- **Eval dataset hand-off**: gates ship green on placeholder fixtures. The moment a real dataset lands, the corresponding threshold in `eval_thresholds.yaml` must be raised in the same PR — otherwise we ship the placeholder bar to `main`.
- **CI runtime budget**: with all four eval gates + smoke + image build, the pipeline may exceed the team's agreed budget on first run. tasks.md should include a measure step and, if needed, a parallelization plan (image build in parallel with lint/typecheck).
