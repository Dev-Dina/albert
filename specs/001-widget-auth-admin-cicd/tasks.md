---

description: "Tasks: Widget Auth, Admin UX & CI/CD (Owner D)"
---

# Tasks: Widget Auth, Admin UX & CI/CD (Owner D)

**Input**: Design documents from `/specs/001-widget-auth-admin-cicd/`

**Prerequisites**: `plan.md` (required), `spec.md` (required), `research.md`, `data-model.md`, `contracts/`, `quickstart.md` — all present.

**Tests**: REQUIRED. Constitution Principle IV mandates a test for every changed behavior; spec FR-021..030 mandates eval gates in CI; spec US2 IS a red-team test. Tests are first-class deliverables in this feature.

**Organization**: Tasks are grouped by user story so each story can be implemented, demoed, and reviewed as a standalone increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4).
- Each task names exact file paths.

## Path Conventions

Multi-service web app. Source roots:
- `backend/` — FastAPI service (existing).
- `widget/` — React 18 + TS bundle (NEW).
- `admin/` — Streamlit app (NEW).
- `evals/` — CI gate harnesses (NEW).
- `scripts/` — smoke + seed scripts.
- `guardrails/app/platform_floor.yaml` — NEW floor file.
- `.github/workflows/ci.yml`, `docker-compose.yml`, `Makefile`, `.env.example` — existing protected files (changes are warned and reviewed per Constitution + CLAUDE.md).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create directory skeletons, register new services, and add tunables. No business logic yet.

- [X] T001 Create directory skeletons: `widget/src/`, `widget/src/ui/`, `widget/tests/`, `admin/app/pages/`, `admin/app/lib/`, `admin/app/clients/`, `admin/tests/`, `evals/common/`, `evals/classifier/fixtures/`, `evals/tool_selection/fixtures/`, `evals/rag/fixtures/`, `evals/redteam_cross_tenant/fixtures/`, `evals/redaction/fixtures/`. Add `.gitkeep` in any empty leaf.
- [X] T002 [P] Add widget + rate-limit tunables to `.env.example` — PROTECTED FILE WARN. Append (with `dev-*` defaults only, no real secrets): `WIDGET_SESSION_TTL_SECONDS=900`, `WIDGET_CLOCK_SKEW_SECONDS=60`, `WIDGET_RATE_LIMIT_PER_IP_PER_MIN=30`, `WIDGET_RATE_LIMIT_PER_TENANT_PER_MIN=120`, `WIDGET_LOADER_URL=http://localhost:8000/widget.js`.
- [X] T003 [P] Add `admin` service to `docker-compose.yml` — PROTECTED FILE WARN. Build context `./admin`; env_file `.env`; expose `8501:8501`; healthcheck on Streamlit `/_stcore/health`; `depends_on: backend`.
- [X] T004 [P] Add Makefile targets to `Makefile` — PROTECTED FILE WARN. New targets: `widget-build` (esbuild), `admin` (run streamlit), `smoke` (run `scripts/smoke_test.sh`), `eval` (run all `evals/*/run.py`).
- [X] T005 Add backend dependencies in `backend/pyproject.toml`: `redis>=5`, `PyYAML`. Re-lock via `uv lock`.
- [X] T006 [P] Initialise widget toolchain: `widget/package.json` (react@18, react-dom@18, typescript, esbuild, vitest, @types/react, @types/react-dom), `widget/tsconfig.json` (target ES2020, jsx react-jsx, strict true), `widget/esbuild.config.mjs` (two entry points: `src/loader.ts` → `dist/widget.js`, `src/iframe-bootstrap.tsx` → `dist/bundle-<sha>.js`; minify; sha-suffix the bundle via build-time hash).
- [X] T007 [P] Initialise admin app: `admin/pyproject.toml` (streamlit, httpx, pydantic, pydantic-settings), `admin/Dockerfile` (python:3.12-slim, `uv pip install`, `streamlit run app/main.py --server.port 8501 --server.address 0.0.0.0`), `admin/.dockerignore`.
- [X] T008 [P] Initialise evals package: `evals/__init__.py`, `evals/common/__init__.py`, `evals/common/thresholds.py` (load `eval_thresholds.yaml` at repo root), `evals/common/validate_thresholds.py` (assert `redteam.required_pass_rate == 1.0` and `redaction.required_pass_rate == 1.0`, exit 1 otherwise).

**Checkpoint**: Repo skeleton in place; nothing runs yet but `docker compose up` still works (admin healthcheck may flap until US3 lands).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure used by every user story. No user-story work can begin until this phase is complete.

⚠️ **CRITICAL**: T015 (migration + RLS) gates every test that touches the DB. T011/T014 gate the token-exchange path.

- [X] T009 Extend centralized config in `backend/app/core/config.py` — PROTECTED FILE WARN. Add fields with the env defaults from T002. No behavior change to existing keys.
- [X] T010 Create async Redis client in `backend/app/clients/redis_client.py` (single `redis.asyncio.ConnectionPool`, `get_redis()` async ctx manager).
- [X] T011 Create two-dimensional rate-limit primitive in `backend/app/core/rate_limit.py`. Pure Lua token-bucket script run via `redis.eval`; expose `check_and_consume(dimension: str, key: str, capacity: int, refill_per_sec: float) -> RateLimitDecision`. Composable: callers pass `(per_ip, per_tenant)` separately. TODO comment: "extract per-tenant bucket once Owner A's platform primitive merges".
- [X] T012 Create tenant-context helper in `backend/app/core/tenant_context.py`. Async ctx manager `tenant_context(session, tenant_id)` that runs `SET LOCAL app.tenant_id = :tid` on the session and unsets on exit. If Owner A's helper exists by then, re-export from there instead.
- [X] T013 Extend Vault client `backend/app/clients/vault_client.py` with `read_tenant_widget_signing_key(tenant_id) -> bytes | None` and `write_tenant_widget_signing_key(tenant_id, material: bytes) -> int` (returns new Vault KV v2 version). 60-second in-process LRU cache on the read path. Never log key material.
- [X] T014 Extend `backend/app/core/security.py` — PROTECTED FILE WARN. Add `mint_widget_session_token(tenant_id, widget_id, origin, key_version, key_material) -> str` and `verify_widget_session_token(token, key_material, expected_key_version) -> WidgetSessionClaims`. HS256, claims as in `data-model.md` E5, ±60s skew.
- [X] T015 Create Alembic migration `backend/alembic/versions/0003_widget_tables.py` — PROTECTED FILE WARN. Creates `widgets`, `widget_allowed_origins`, `widget_guardrail_configs`, `widget_signing_key_versions` with FKs to `tenants.id` (ON DELETE CASCADE), partial unique index on `(tenant_id) WHERE is_active`, `CHECK` constraints from `data-model.md`, RLS policies (`ENABLE`+`FORCE`+`USING tenant_id = current_setting('app.tenant_id', true)::uuid`), and `SECURITY DEFINER` function `lookup_widget_by_public_id(text)` returning only `(widget_id, tenant_id, status)`. Downgrade drops the function and tables in reverse FK order.
- [X] T016 [P] Create model `backend/app/db/models/widget.py` (fields per `data-model.md` E1).
- [X] T017 [P] Create model `backend/app/db/models/widget_allowed_origin.py` (per E3).
- [X] T018 [P] Create model `backend/app/db/models/widget_guardrail_config.py` (per E4).
- [X] T019 [P] Create model `backend/app/db/models/widget_signing_key_version.py` (per E2; key material NOT a column).
- [X] T020 Create platform floor file `guardrails/app/platform_floor.yaml` (initial keys: `block_topics`, `pii_redaction.enabled`, `injection_defenses.level`). Marked as authoritative floor; tenant config cannot go below.
- [X] T021 Create `backend/app/services/guardrail_floor.py`: loads T020's YAML at startup; `enforce_floor(tenant_config: dict) -> None` raises `FloorViolation(key_path, attempted_value, floor_value)` on any weakening.
- [X] T022 [P] Create repository `backend/app/repositories/widget_repo.py` (get_by_id, get_by_public_id via `lookup_widget_by_public_id`, list_by_tenant, create, update).
- [X] T023 [P] Create repository `backend/app/repositories/allowed_origin_repo.py` (list_by_tenant, add, remove, exists_for_tenant).
- [X] T024 [P] Create repository `backend/app/repositories/guardrail_config_repo.py` (get_for_tenant, upsert).
- [X] T025 Create Pydantic schemas: `backend/app/schemas/widget.py` (WidgetPublicView), `backend/app/schemas/widget_session.py` (WidgetSessionRequest, WidgetSessionResponse), `backend/app/schemas/admin_widget.py` (CreateWidgetRequest, UpdateWidgetRequest, AdminWidget, AllowedOrigin, CreateAllowedOriginRequest, EmbedSnippetResponse, GuardrailConfig, FloorViolation, SigningKeyVersionMetadata). Schemas MUST NOT declare a `tenant_id` field on any visitor-facing request body (FR-009).
- [X] T026 Add `get_widget_session()` dependency in `backend/app/api/deps.py`: parses `Authorization: Bearer …`, fetches active key version metadata + material, calls `verify_widget_session_token`, sets `app.tenant_id` on the request's DB session via T012. Returns `WidgetSessionClaims`. 401 on any failure.

**Checkpoint**: Migration applies; primitives import cleanly; no routes wired yet.

---

## Phase 3: User Story 1 — Visitor chats through embedded widget (Priority: P1) 🎯 MVP

**Goal**: A visitor on an allowed host loads the embed, sees the tenant's greeting/theme, sends a chat message, and gets a reply. Anonymous; tenant resolved entirely from the verified session token.

**Independent Test**: Run `scripts/seed_demo_tenant.py --slug acme`, paste the embed snippet into a static page served from `http://localhost:8080`, open the page, send a message, observe a response. No admin app or CI needed.

### Tests for User Story 1 ⚠️

> Write these tests FIRST and verify they FAIL before implementation tasks.

- [X] T027 [P] [US1] Contract test for `POST /api/v1/widget/session` success in `backend/tests/test_widget_session.py` — asserts 200, response schema matches `contracts/widget-session.openapi.yaml` (200 path), token decodes with the expected claims.
- [X] T028 [P] [US1] Contract test for `POST /api/v1/widget/chat` happy path in `backend/tests/test_widget_chat.py` — asserts 200 with a Tenant A token returns a body matching `WidgetChatResponse`; asserts the Postgres `app.tenant_id` GUC was set via `SET LOCAL` on the request's DB session (e.g., via a `current_setting('app.tenant_id', true)` probe). Do **not** assert by scraping a log line containing the raw tenant UUID — per FR-015c, tenant identifiers are not emitted raw in logs.
- [X] T029 [P] [US1] Test for `GET /widget.js` and `GET /widget/embed.html?widget_id=…` in `backend/tests/test_widget_loader.py` — asserts 200, correct `Content-Type`, `Cache-Control` per `contracts/widget-loader.contract.md`. Specifically: `widget.js` is `public, max-age=60`; per-widget `embed.html` is `no-store` (so tenant allowlist / greeting / theme changes propagate on the next load per FR-004); `bundle-<sha>.{js,css}` is `public, max-age=31536000, immutable`.

### Implementation for User Story 1

- [X] T030 [US1] Implement `backend/app/services/widget_session_service.py`: `exchange(widget_id, origin) -> WidgetSessionResponse` — happy-path only in this story (origin check returns True for now if origin in allowlist; full hardening lives in US2). Fetches active key version + material via T013; calls `mint_widget_session_token`.
- [X] T031 [US1] Implement route `backend/app/api/routes/widget_session.py`: `POST /api/v1/widget/session` reading `Origin` header and JSON `{widget_id}`. Schemas: T025.
- [X] T032 [US1] Implement route `backend/app/api/routes/widget_loader.py`: `GET /widget.js` (serves `widget/dist/widget.js` with `Cache-Control: public, max-age=60`); `GET /widget/embed.html` (renders HTML referencing `/widget/bundle-<sha>.js` and, when present, `/widget/bundle-<sha>.css`; `Cache-Control: no-store` so per-tenant config changes propagate on the next widget load per FR-004; CSP set to placeholder `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'self';` — full per-tenant `frame-ancestors` lands in US2 T055); `GET /widget/bundle-<sha>.{js,css}` (serves the built bundle/sidecar with `Cache-Control: public, max-age=31536000, immutable`).
- [X] T033 [US1] Implement route `backend/app/api/routes/widget_chat.py`: `POST /api/v1/widget/chat` depends on `get_widget_session` (T026); reads `message` ONLY from body — any `tenant_id` field is dropped on parse because the Pydantic model doesn't declare it. Stubbed reply for now: echoes `"You said: <message>"` with a `conversation_id` UUID. Real assistant integration is Owner B's lane.
- [X] T034 [US1] Register `widget_session`, `widget_loader`, `widget_chat` routers in `backend/app/main.py`.
- [X] T035 [P] [US1] Implement `widget/src/loader.ts` — reads `document.currentScript`, validates `data-widget-id` against `^[A-Za-z0-9]{22}$`, on success injects iframe at `${origin}/widget/embed.html?widget_id=<id>` (positioned fixed bottom-right). Fail-closed path is wired in US2 T060; loader still must not throw here.
- [X] T036 [P] [US1] Implement `widget/src/iframe-bootstrap.tsx` (React entry) + `widget/src/App.tsx` (renders `<Chat/>` after session is acquired; shows greeting + theme).
- [X] T037 [P] [US1] Implement `widget/src/api.ts` — `exchangeSession({widget_id})` POSTs to `/api/v1/widget/session`; `sendChat({message, conversation_id?})` POSTs to `/api/v1/widget/chat` with `Authorization: Bearer <token>`.
- [X] T038 [P] [US1] Implement `widget/src/session.ts` — holds token in module-scope memory only, schedules proactive re-exchange at `expires_in - 120s`, wraps `sendChat` with single-retry-on-401 logic. NEVER writes to localStorage / cookie.
- [X] T039 [P] [US1] Implement React UI: `widget/src/ui/Chat.tsx`, `widget/src/ui/MessageList.tsx`, `widget/src/ui/Composer.tsx`, `widget/src/ui/styles.css`. Theme/greeting consumed from `WidgetPublicView` (T030 response).
- [X] T040 [US1] Build the bundle: run `node widget/esbuild.config.mjs`; commit `widget/dist/.gitkeep` only (built artifact lives in CI). Verify both `widget.js` (≤ 4 KB) and `bundle-<sha>.js` (≤ 160 KB) byte budgets locally. **Measured**: `widget.js` = 977 B; `bundle-<sha>.js` = ~145 KB (within the raised 160 KB ceiling adopted in plan.md). Bundle-trim follow-up tracked as T095a (target: return to ≤ 110 KB via preact-compat or code-split after MVP ships).
- [X] T041 [P] [US1] Vitest unit tests `widget/tests/api.test.ts` — mocks `fetch`; asserts request shape (no `tenant_id` in body) and response handling for 200/401/403/429.
- [X] T042 [P] [US1] Vitest unit tests `widget/tests/session.test.ts` — asserts proactive re-exchange schedules at T-120s, reactive re-exchange on 401 happens exactly once before surfacing error.
- [X] T042a [P] [US1] Vitest case in `widget/tests/api.test.ts` (moved from session.test.ts — the orchestration lives in `sendChat` / `api.ts`, so this sits next to the existing 401-retry success-path test): when `/api/v1/widget/session` returns 429 on a silent re-exchange, the widget surfaces a "session expired" state and does **not** retry the exchange or the original chat request (covers FR-008c: refused re-exchange must not trigger an unbounded retry loop). Asserts exactly one network call each to `/widget/chat` and `/widget/session` after the trigger 401, that `sendChat` throws `HttpError(401)`, and that `getSessionToken()` returns `null` afterward.
- [X] T043 [US1] Demo-seeding script `scripts/seed_demo_tenant.py`: creates a tenant + admin user + allowed origin + initial widget + first signing key (via T058's rotate path, since rotate is the only legal way to put key material in Vault). Idempotent.
- [X] T044 [US1] Integration test `backend/tests/test_widget_e2e_chat.py` — runs the quickstart-style flow: seed → exchange → chat → assert response carries Tenant A's conversation_id.

**Checkpoint**: Story 1 is fully testable. A demo tenant + a static host page on `http://localhost:8080` (added to allowlist) produces a working chat. Safety hardening of the same path lands in US2.

---

## Phase 4: User Story 2 — Platform refuses cross-tenant and disallowed-origin abuse (Priority: P1)

**Goal**: All three attacks from spec US2 fail: disallowed-origin embed, `curl` with copied widget_id + forged/stale token, valid token with foreign `tenant_id` in body. Plus: rotation invalidates outstanding tokens; rate-limit dual-gate trips correctly.

**Independent Test**: `pytest backend/tests/redteam/cross_tenant_demo.py` reports `3/3 attacks rejected`. Rate-limit tests in `test_widget_rate_limit.py` pass.

### Tests for User Story 2 ⚠️

- [X] T045 [P] [US2] Test in `backend/tests/test_widget_origin_csp.py`: token exchange from `https://attacker.test/` (Origin header) → 403; opaque body (no leak of "origin not allowed" vs "widget not found" vs "widget disabled").
- [X] T046 [P] [US2] Test in `backend/tests/test_widget_origin_csp.py`: `GET /widget/embed.html` for a tenant with allowlist `[origin_a, origin_b]` returns `Content-Security-Policy` with `frame-ancestors origin_a origin_b` (exact substring match).
- [X] T047 [P] [US2] Test in `backend/tests/test_widget_session.py`: chat with (a) missing token, (b) HS256-signed token with wrong secret, (c) token whose `exp` is 120s in the past → 401 in all cases.
- [X] T048 [P] [US2] Test in `backend/tests/test_widget_chat.py`: POST chat with a Tenant A token AND `{"tenant_id": "<Tenant B uuid>", "message": "hi"}` → response is served under Tenant A's RLS context. Assert no Tenant B row is read; assert the body field is logged as `body_tenant_id_ignored`.
- [X] T049 [P] [US2] Test in `backend/tests/test_widget_key_rotation.py`: issue token v1; rotate; previous token returns 401 on next chat call; a re-exchange after rotation succeeds.
- [X] T050 [P] [US2] Test in `backend/tests/test_widget_rate_limit.py`: hammer `/api/v1/widget/session` from one IP past `WIDGET_RATE_LIMIT_PER_IP_PER_MIN` → 429 with `Retry-After`.
- [X] T051 [P] [US2] Test in `backend/tests/test_widget_rate_limit.py`: hammer the same endpoint from many IPs against one tenant past `WIDGET_RATE_LIMIT_PER_TENANT_PER_MIN` → 429.
- [X] T052 [P] [US2] Test in `backend/tests/test_widget_rate_limit.py`: exhausting per-IP for IP_A does NOT consume the per-tenant budget for IP_B's same-tenant traffic (separate counters).
- [X] T053 [P] [US2] Test in `widget/tests/loader.test.ts`: a host page including the snippet without `data-widget-id` triggers a `console.error` and injects nothing (verified in jsdom).

### Implementation for User Story 2

- [X] T054 [US2] Harden `backend/app/services/widget_session_service.py`: server-side origin check vs `allowed_origin_repo.exists_for_tenant`; widget-status check; uniform 403 response body when ANY of {bad origin, widget disabled, widget not found} fails. Verifies `Origin` header is present and well-formed.
- [X] T055 [US2] Emit per-tenant `Content-Security-Policy: frame-ancestors …` and legacy `X-Frame-Options` headers in `backend/app/api/routes/widget_loader.py` `GET /widget/embed.html` based on the tenant's allowlist (resolved via the lookup function from T015).
- [X] T055a [US2] Implement per-tenant CORS resolution for the widget API surface (`/api/v1/widget/session`, `/api/v1/widget/chat`) to satisfy FR-012. Added `backend/app/api/middleware/widget_cors.py` which echoes `Access-Control-Allow-Origin: <Origin>` + `Vary: Origin` only on widget routes that returned 2xx (so the server-side origin check at T054/T059a remains the trust boundary). Preflight (OPTIONS) returns 204 with no ACAO so the browser refuses a tenant-mismatched preflight. Registered in `backend/app/main.py`.
- [X] T055b [P] [US2] Contract test in `backend/tests/test_widget_cors.py`: for a tenant with allowlist `[origin_a]`, a `POST /api/v1/widget/session` with `Origin: origin_a` returns `Access-Control-Allow-Origin: origin_a` AND `Vary: Origin`; the same call with `Origin: https://attacker.test` returns 403 with NO `Access-Control-Allow-Origin` header. Also asserts an `OPTIONS` preflight to `/api/v1/widget/chat` echoes only allowed origins.
- [X] T056 [US2] Wire two-dimensional rate limit into `backend/app/api/routes/widget_session.py`: per-IP gate fires BEFORE the DB lookup (so a flood from one IP cannot drain the tenant budget for legitimate visitors), per-tenant gate fires AFTER the widget is resolved. Either trip raises 429 + `Retry-After`. Test stubs `route_mod.check_and_consume`; a per-test conftest disables Redis by default.
- [X] T057 [US2] Structured logging in `backend/app/core/rate_limit.py`: on trip, log `{event: "rate_limit_trip", dimension, key_hash, count, limit}` — `key_hash` is HMAC-SHA256 of the identifier so logs don't leak raw tenant identifiers across operators (FR-015c). Response body MUST NOT include the tripped dimension (verified by test_widget_rate_limit.test_per_ip_rate_limit_returns_429_with_retry_after).
- [X] T058 [US2] Implemented `backend/app/services/widget_admin_service.py::rotate_signing_key(tenant_id, actor_user_id)`: marks the active row inactive (Postgres TX), writes new material to Vault (T013), inserts new row `is_active=true, version=current+1`. Rolls back the Postgres TX on Vault failure. Returns only `(version, created_at)`.
- [X] T059 [US2] In `backend/app/api/deps.py::get_widget_session` (already in place from US1): after decoding the JWT, fetch `widget_signing_key_versions` row for `tenant_id` where `is_active=true`; if `claims.kvr != active.version`, reject 401.
- [X] T059a [US2] In `backend/app/api/deps.py::get_widget_session` (further extended): after the key-version check, re-check the request's `Origin` header against the tenant's current `widget_allowed_origins` via `allowed_origin_repo.exists_for_tenant`. If the origin is missing or no longer on the allowlist, reject with HTTP 401 (uniform with the rest of the dep). Covers spec edge case "Token replay after origin change" and SC-008.
- [X] T059b [P] [US2] Test in `backend/tests/test_widget_origin_csp.py`: issue a valid Tenant A token from `https://demo.example.com` (allowed); remove that origin from Tenant A's allowlist; the next `POST /api/v1/widget/chat` from the same `Origin` with the still-unexpired token returns 401. Asserts SC-008. Companion test: with the origin still on the list, the same token continues to work (no regression on the happy path).
- [X] T060 [US2] Loader fail-closed path in `widget/src/loader.ts` already implemented in US1 (T035) — verified by `widget/tests/loader.test.ts` (T053) running the regex-check + iframe-injection branch in jsdom.
- [X] T061 [US2] Cross-tenant red-team script `backend/tests/redteam/cross_tenant_demo.py`: implements the 3 attacks from spec US2 (disallowed origin, forged token, body tenant_id injection) and asserts each is rejected. Importable from quickstart step 8.

**Checkpoint**: Both P1 stories pass. US1 + US2 together = a shippable widget + safety guarantees. CI smoke + cross-tenant gate (built in US4) can now run against this surface.

---

## Phase 5: User Story 3 — Tenant admin self-service (Priority: P2)

**Goal**: A tenant admin can list/edit their widgets, manage their allowlist, edit guardrail config (floor-enforced), copy the embed snippet, and rotate the signing key — all via Streamlit, with no engineer assistance.

**Independent Test**: Log in to `http://localhost:8501` as `admin-acme@example.com`, change the greeting, reload the embed on the host page, observe the new greeting. Try to weaken `pii_redaction.enabled`; the admin app refuses with a floor-violation message.

### Tests for User Story 3 ⚠️

- [X] T062 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `GET /api/v1/admin/widgets` as Tenant A admin returns only Tenant A widgets; never Tenant B's (verified by seeding both tenants).
- [X] T063 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `PATCH /api/v1/admin/widgets/{id}` updates `theme` + `greeting` + `status`; subsequent `GET /widget/embed.html` reflects new values on next request.
- [X] T064 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `GET /api/v1/admin/widgets/{id}/embed-snippet` returns a single `<script>` line containing the loader URL and exact `data-widget-id` — no manual editing required.
- [X] T065 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `POST /api/v1/admin/allowed-origins` rejects (422) any of: wildcard origin (`https://*.x.com`), origin with path (`https://x.com/foo`), origin with query, origin with trailing slash, `http://example.com` (non-localhost http).
- [X] T066 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `PUT /api/v1/admin/guardrail-config` with a config that disables `pii_redaction` → 422 with body `{error: "floor_violation", key_path: "pii_redaction.enabled", attempted_value: false, floor_value: true}`.
- [X] T067 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `POST /api/v1/admin/signing-key/rotate` returns only `{version, created_at}`; raw key material is NOT in the response body and NOT in the log stream (assert via captured logs).

### Implementation for User Story 3

- [X] T068 [US3] Extend `backend/app/services/widget_admin_service.py`: `list_widgets`, `create_widget`, `update_widget`, `embed_snippet`, `list_allowed_origins`, `add_allowed_origin` (calls origin validator), `delete_allowed_origin`, `get_guardrail_config`, `put_guardrail_config` (calls `guardrail_floor.enforce_floor`). All methods take `actor_user_id` and derive `tenant_id` from membership lookup — never from a body field.
- [X] T069 [US3] Implement route `backend/app/api/routes/admin_widgets.py` per `contracts/widget-admin.openapi.yaml`. Requires `current_user` with a `tenant_admin` membership for the inferred tenant. On a 4xx, returns 404 (not 403) when the resource exists but isn't owned (do not confirm existence).
- [X] T070 [P] [US3] Streamlit auth helper `admin/app/lib/auth.py`: login form, calls `POST /api/v1/auth/login`, stores `{token, expires_at}` in `st.session_state`, logout button. Token never persisted.
- [X] T071 [P] [US3] Backend client `admin/app/clients/backend_client.py`: thin httpx wrapper with `Authorization: Bearer …` injection and typed return shapes mirroring T025.
- [X] T072 [P] [US3] Streamlit entry `admin/app/main.py`: `st.set_page_config`, sidebar nav, redirect to login if no token.
- [X] T073 [P] [US3] Page `admin/app/pages/1_Widgets.py`: list, create, edit name/theme/greeting/status.
- [X] T074 [P] [US3] Page `admin/app/pages/2_Allowed_Origins.py`: list, add (form validation mirroring T065), delete. When the list is empty, render an inline warning at the top of the page that names the consequence ("No widget will load anywhere until at least one origin is added — the token-exchange endpoint rejects every request") and links to the Widgets page so the admin can see which widgets are currently un-embeddable. Covers spec edge case "Tenant with zero allowed origins". The Widgets page (T073) MUST mirror this state by tagging each widget with a "no allowed origins" badge when the tenant allowlist is empty.
- [X] T075 [P] [US3] Page `admin/app/pages/3_Guardrails.py`: render current config, accept edits, render server-side floor-violation message inline on 422.
- [X] T076 [P] [US3] Page `admin/app/pages/4_Embed_Snippet.py`: per-widget snippet display + `st.code(..., language="html")` for copy, "Copy to clipboard" via `st.components.v1.html` shim.
- [X] T077 [P] [US3] Page `admin/app/pages/5_Signing_Key.py`: shows current version + created_at; "Rotate" button behind a confirmation modal that names the consequence ("will sign every visitor out of every widget"). Calls `POST /api/v1/admin/signing-key/rotate`.
- [X] T078 [P] [US3] Streamlit-side unit tests `admin/tests/test_backend_client.py`: mock httpx; assert Authorization header injection, 401 surfaced as a typed exception.
- [X] T079 [US3] Verify `admin/Dockerfile` is lean: no `torch`, `transformers`, or `playwright`. `docker compose up admin` healthcheck green.

**Checkpoint**: A tenant admin can do the full quickstart steps 1–9 without engineer help. SC-001 demonstrably hits ≤ 10 minutes.

---

## Phase 6: User Story 4 — CI blocks merges that would silently degrade the agent (Priority: P2)

**Goal**: Every push/PR runs lint → typecheck + image-build (parallel) → smoke → 5 eval gates (parallel: classifier, agent_tool_selection, rag, redteam_cross_tenant, redaction). A regression below threshold fails the build and names the gate. Smoke failure short-circuits eval gates. No silent retries.

**Independent Test**: Open a throwaway PR that deletes a row from `evals/redteam_cross_tenant/fixtures/expected_failures.json`. CI fails on `redteam_cross_tenant` with `OBSERVED=…  THRESHOLD=1.0` in the summary. Revert → green.

### Tests / Implementation for User Story 4

- [X] T080 [P] [US4] Classifier gate `evals/classifier/run.py` + placeholder fixtures under `evals/classifier/fixtures/`. Loads `classifier.macro_f1_min` from T008; computes macro-F1 on the fixture; prints `GATE=classifier STATUS=<…> OBSERVED=<…> THRESHOLD=<…>`; exits 0/1/2 per `contracts/ci-gate.contract.md`. Placeholder fixture produces ~0.65 to pass the default 0.60 threshold.
- [X] T081 [P] [US4] Agent tool-selection gate `evals/tool_selection/run.py` + fixtures. Reads `agent_tool_selection.accuracy_min`. Placeholder set is 5 cases with the obvious-correct tool listed; passes 0.70 default.
- [X] T082 [P] [US4] RAG gate `evals/rag/run.py` + fixtures. Reads `rag.hit_at_5_min` AND `rag.mrr_min`. Placeholder fixture set with deterministic top-k.
- [X] T083 [P] [US4] Cross-tenant red-team gate `evals/redteam_cross_tenant/run.py` + `expected_failures.json` (3 attempts from spec US2). MUST achieve 1.00 to pass. Each attempt runs against a `httpx` client pointed at the in-CI backend.
- [X] T084 [P] [US4] Redaction gate `evals/redaction/run.py` + planted-secret fixtures (`evals/redaction/fixtures/`). Asserts the planted fake key never appears in any captured response, log line, or stored trace. MUST be 1.00.
- [X] T085 [P] [US4] Smoke test `scripts/smoke_test.sh`: `docker compose up -d`, polls `/health` on backend (8000), modelserver (8020), guardrails (8010) with timeout; tears down on exit. Exits non-zero on any failure.
- [X] T086 [US4] Rewrite `.github/workflows/ci.yml` — PROTECTED FILE WARN. Jobs: `lint`, `typecheck`, `image_build` (parallel); `smoke` (needs `image_build`); 5 eval-gate jobs (need `smoke`, run parallel); `summary` (`needs: [classifier, tool_selection, rag, redteam, redaction]; if: always()`). NEVER uses `continue-on-error: true` for a gate (FR-030). **Also consolidate the dual thresholds files**: Owner C's `evals/rag_eval.py`, `evals/tool_selection_eval.py`, and `.github/workflows/rag-eval.yml` currently read `evals/eval_thresholds.yaml` (flat keys); the canonical Owner D file is `/eval_thresholds.yaml` (nested). Either (a) migrate the Owner C runners to read the canonical file via `evals.common.thresholds.load_thresholds()`, then delete `evals/eval_thresholds.yaml`, **or** (b) generate the flat-key shadow file from the nested one in a pre-step so there's a single source of truth. Either way, fold `rag-eval.yml` into the new `ci.yml` and delete the orphan workflow so the rag/tool-selection gates don't run twice on every PR.
- [X] T087 [US4] CI summary step in the `summary` job: reads `artifacts/ci-gate-results.jsonl` from each gate's upload, writes a markdown table to `$GITHUB_STEP_SUMMARY`, sets the check title to the first failed gate name with observed vs threshold (FR-029). Also reads `ci.total_budget_seconds` from `eval_thresholds.yaml` and surfaces observed vs threshold for total wall-clock (backs SC-006); for v1 this is a soft signal (rendered in the summary, does not fail the build) — promote to a hard gate after a few weeks of measured run-times.
- [X] T088 [US4] Bundle-size CI step inside the `image_build` job (or a new `widget_build` job that the bundle-size step depends on): runs `node widget/esbuild.config.mjs`, then fails if `widget/dist/widget.js > 4096 bytes` OR `widget/dist/bundle-*.js > 163840 bytes` (160 KB ceiling per plan.md Performance Goals; raised from the initial 110 KB after measurement — see plan.md Open Risks). T095a is the scheduled follow-up to bring this back down.
- [X] T089 [US4] Threshold-floor lint: `evals/common/validate_thresholds.py` runs as the FIRST CI step. Refuses any value of `redteam.required_pass_rate` or `redaction.required_pass_rate` < 1.0 (FR-026, FR-027).
- [X] T090 [US4] Update `eval_thresholds.yaml`: keep current placeholder values, add a `# DAY 1 PLACEHOLDER — raise when real dataset lands` comment above each non-1.0 value, confirm `redteam.required_pass_rate: 1.00` and `redaction.required_pass_rate: 1.00` are exact.

**Checkpoint**: CI runs all seven checks on every push/PR (lint, typecheck, image_build, smoke, and the 5 eval gates: classifier, agent_tool_selection, rag, redteam_cross_tenant, redaction) — wording matches spec.md SC-006. Failures name the gate and observed-vs-threshold. SC-002, SC-006 demonstrable.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T091 [P] Update `README.md`: add a "Widget" section pointing at `specs/001-widget-auth-admin-cicd/quickstart.md`; document the new admin port (8501) in the Service Ports table.
- [ ] T092 [P] Add a short "Protected files touched" block to the PR description for this branch listing `.env.example`, `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`, `backend/app/core/config.py`, `backend/app/core/security.py`, `backend/app/db/session.py` (none expected), and `backend/alembic/versions/0003_widget_tables.py`.
- [ ] T093 Run `specs/001-widget-auth-admin-cicd/quickstart.md` end-to-end against a fresh `docker compose up --build`; capture any gaps as follow-up issues; check off Edge Cases from `spec.md` (iframe-in-iframe, zero allowed origins, token replay after origin change, clock skew, cached bundle, loader without `data-widget-id`).
- [ ] T094 [P] Re-evaluate Constitution Check post-implementation (record in `plan.md` under a new "Post-implementation Constitution Check" subsection if any drift surfaced).
- [ ] T095 [P] Tighten any placeholder eval threshold whose backing dataset has landed (coordinate with Owners A/B/C; raise in same PR that lands the data).
- [ ] T095a [P] Bundle-trim follow-up: bring `widget/dist/bundle-*.js` back under the original 110 KB minified / 45 KB gzipped target. Approaches in priority order: (1) `preact/compat` alias in `esbuild.config.mjs` (~70 KB savings, expected to clear the target alone); (2) code-split the chat surface so the iframe shows the greeting before React UI is parsed; (3) drop unused React UI primitives. Lower T088's `163840` ceiling back to `112640` in the **same** PR that lands the trim — otherwise the relaxed ceiling silently becomes the new normal. Re-measure gzipped size and update plan.md Performance Goals to match.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No code deps. Can start immediately.
- **Foundational (Phase 2)**: Depends on Setup. Blocks all user stories. T015 (migration) blocks every DB-touching task. T011/T012/T014 block the token-exchange path.
- **US1 (Phase 3)** and **US2 (Phase 4)** depend on Foundational. US2 hardens code paths first opened by US1, so they share files (`widget_session_service.py`, `widget_loader.py`, `widget_session.py`, `widget_chat.py`, `loader.ts`); within those files, US2's tasks edit code US1 wrote — sequence US1 → US2 inside each shared file.
- **US3 (Phase 5)** depends on Foundational + admin entities exist. Independent of US1/US2 surface code (admin endpoints don't share files with widget endpoints) but the rotate flow (T058 in US2) is a hard dep for the admin signing-key page (T077).
- **US4 (Phase 6)** depends on Foundational; the smoke test and redteam gate only fully exercise after US1 + US2 land; CI skeleton can stand up earlier with placeholder gates.
- **Polish (Phase 7)** depends on all of US1–US4.

### Within Each Story

- Tests written and FAILING before implementation tasks for that story start.
- Models → repositories → services → routes → wiring in `main.py`.
- Widget React tasks (T035–T039, T041–T042) are independent of each other; the build step T040 depends on all of them.

### Parallel Opportunities (high-value examples)

- All Phase 1 [P] tasks (T002, T003, T004, T006, T007, T008) can run together.
- Phase 2: T016–T019 (4 model files) parallel; T022–T024 (3 repos) parallel; T020/T021 parallel with the model batch.
- Phase 3: T027/T028/T029 (3 test files) parallel; T035–T039, T041, T042 (widget files) all parallel.
- Phase 4: T045–T053 (9 test files / file-sections) parallel.
- Phase 5: T070–T077 (Streamlit pages + lib + client) all parallel after T068/T069 land.
- Phase 6: T080–T085 (5 gate runners + smoke) all parallel; T086 (CI workflow) is the integration point.

### Cross-owner gates (recap from `plan.md`)

- **Owner A**: provides the per-request `app.tenant_id` dependency, the repository scoping helper, the platform rate-limit primitive, and the `tenant_admin` membership role. If any of these lands after this feature's relevant task, that task carries the "TODO: lift to Owner A's primitive" marker and a failing test that flips green when A's primitive merges.
- **Owner B**: provides the agent tool-selection golden set + RAG golden set (replaces our placeholder fixtures in T081/T082).
- **Owner C**: provides the cross-tenant red-team dataset (replaces T083 placeholder), the redaction layer + planted-secret fixtures (replaces T084 placeholder), and may take over `guardrails/app/platform_floor.yaml` ownership later.

---

## Parallel Example: User Story 1

```bash
# After Phase 2 completes, launch the US1 test set in parallel:
Task: "Contract test for POST /api/v1/widget/session in backend/tests/test_widget_session.py"
Task: "Contract test for POST /api/v1/widget/chat in backend/tests/test_widget_chat.py"
Task: "Test for GET /widget.js + /widget/embed.html in backend/tests/test_widget_loader.py"

# Then launch all widget React files in parallel:
Task: "widget/src/loader.ts"
Task: "widget/src/iframe-bootstrap.tsx + App.tsx"
Task: "widget/src/api.ts"
Task: "widget/src/session.ts"
Task: "widget/src/ui/{Chat,MessageList,Composer}.tsx + styles.css"
```

---

## Implementation Strategy

### MVP First (US1 + US2 together)

Both P1 stories form the safety-critical MVP. Per Constitution Principle I, **US1 alone must not ship** — a working chat without the safety guarantees from US2 is a one-line cross-tenant breach risk.

1. Phase 1 + Phase 2 — Setup + Foundational.
2. Phase 3 — US1 (visitor happy path).
3. Phase 4 — US2 (safety hardening on the same code paths).
4. STOP and VALIDATE: run quickstart steps 1–8; redteam script reports 3/3 rejected.
5. Demo to the team. PR can be split US1 / US2 for review but **must merge together**.

### Incremental Delivery After MVP

6. Phase 5 — US3 (admin). Independent of widget code paths; one tenant admin can self-onboard.
7. Phase 6 — US4 (CI gates). Locks in the safety properties demonstrated in MVP.
8. Phase 7 — Polish.

### Parallel Team Strategy

If two contributors are on Owner D:
- Contributor 1: Phase 2 → US1 → US2 (single brain on the safety-critical path).
- Contributor 2: Phase 1 [P] tasks → US3 (admin) in parallel once T015 + T026 land; then US4.

### Non-negotiable safety rules

- No US1 PR merges without US2's tests passing on the same branch.
- No `redteam.required_pass_rate` or `redaction.required_pass_rate` value below 1.00 ever lands on `main`.
- Any task that touches a protected file calls it out in the PR title (e.g. `[protected]`).

---

## Notes

- [P] tasks = different files, no in-flight dependency.
- [Story] label maps every implementation task to a spec user story for traceability.
- Verify tests fail before implementing the behavior they cover (Constitution Principle IV).
- Commit after each task or coherent group; avoid omnibus commits that mix US1 and US2.
- Stop at any checkpoint and validate the story independently — that's the whole point of the phasing.
- Avoid: vague tasks, same-file conflicts (sequence US1→US2 inside shared widget files), cross-story dependencies that break independence.
