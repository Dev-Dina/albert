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

- [ ] T027 [P] [US1] Contract test for `POST /api/v1/widget/session` success in `backend/tests/test_widget_session.py` — asserts 200, response schema matches `contracts/widget-session.openapi.yaml` (200 path), token decodes with the expected claims.
- [ ] T028 [P] [US1] Contract test for `POST /api/v1/widget/chat` happy path in `backend/tests/test_widget_chat.py` — asserts 200 with a Tenant A token returns a body matching `WidgetChatResponse`; logs show `app.tenant_id` was set.
- [ ] T029 [P] [US1] Test for `GET /widget.js` and `GET /widget/embed.html?widget_id=…` in `backend/tests/test_widget_loader.py` — asserts 200, correct `Content-Type`, `Cache-Control` per `contracts/widget-loader.contract.md`.

### Implementation for User Story 1

- [ ] T030 [US1] Implement `backend/app/services/widget_session_service.py`: `exchange(widget_id, origin) -> WidgetSessionResponse` — happy-path only in this story (origin check returns True for now if origin in allowlist; full hardening lives in US2). Fetches active key version + material via T013; calls `mint_widget_session_token`.
- [ ] T031 [US1] Implement route `backend/app/api/routes/widget_session.py`: `POST /api/v1/widget/session` reading `Origin` header and JSON `{widget_id}`. Schemas: T025.
- [ ] T032 [US1] Implement route `backend/app/api/routes/widget_loader.py`: `GET /widget.js` (serves `widget/dist/widget.js` with `Cache-Control: public, max-age=60`); `GET /widget/embed.html` (renders HTML referencing `/widget/bundle-<sha>.js`; CSP set to placeholder `default-src 'none'; script-src 'self'; connect-src 'self'; frame-ancestors 'self';` — full per-tenant `frame-ancestors` lands in US2 T055); `GET /widget/bundle-<sha>.js` (serves the built bundle with `Cache-Control: public, max-age=31536000, immutable`).
- [ ] T033 [US1] Implement route `backend/app/api/routes/widget_chat.py`: `POST /api/v1/widget/chat` depends on `get_widget_session` (T026); reads `message` ONLY from body — any `tenant_id` field is dropped on parse because the Pydantic model doesn't declare it. Stubbed reply for now: echoes `"You said: <message>"` with a `conversation_id` UUID. Real assistant integration is Owner B's lane.
- [ ] T034 [US1] Register `widget_session`, `widget_loader`, `widget_chat` routers in `backend/app/main.py`.
- [ ] T035 [P] [US1] Implement `widget/src/loader.ts` — reads `document.currentScript`, validates `data-widget-id` against `^[A-Za-z0-9]{22}$`, on success injects iframe at `${origin}/widget/embed.html?widget_id=<id>` (positioned fixed bottom-right). Fail-closed path is wired in US2 T060; loader still must not throw here.
- [ ] T036 [P] [US1] Implement `widget/src/iframe-bootstrap.tsx` (React entry) + `widget/src/App.tsx` (renders `<Chat/>` after session is acquired; shows greeting + theme).
- [ ] T037 [P] [US1] Implement `widget/src/api.ts` — `exchangeSession({widget_id})` POSTs to `/api/v1/widget/session`; `sendChat({message, conversation_id?})` POSTs to `/api/v1/widget/chat` with `Authorization: Bearer <token>`.
- [ ] T038 [P] [US1] Implement `widget/src/session.ts` — holds token in module-scope memory only, schedules proactive re-exchange at `expires_in - 120s`, wraps `sendChat` with single-retry-on-401 logic. NEVER writes to localStorage / cookie.
- [ ] T039 [P] [US1] Implement React UI: `widget/src/ui/Chat.tsx`, `widget/src/ui/MessageList.tsx`, `widget/src/ui/Composer.tsx`, `widget/src/ui/styles.css`. Theme/greeting consumed from `WidgetPublicView` (T030 response).
- [ ] T040 [US1] Build the bundle: run `node widget/esbuild.config.mjs`; commit `widget/dist/.gitkeep` only (built artifact lives in CI). Verify both `widget.js` (≤ 4 KB) and `bundle-<sha>.js` (≤ 110 KB) byte budgets locally.
- [ ] T041 [P] [US1] Vitest unit tests `widget/tests/api.test.ts` — mocks `fetch`; asserts request shape (no `tenant_id` in body) and response handling for 200/401/403/429.
- [ ] T042 [P] [US1] Vitest unit tests `widget/tests/session.test.ts` — asserts proactive re-exchange schedules at T-120s, reactive re-exchange on 401 happens exactly once before surfacing error.
- [ ] T043 [US1] Demo-seeding script `scripts/seed_demo_tenant.py`: creates a tenant + admin user + allowed origin + initial widget + first signing key (via T058's rotate path, since rotate is the only legal way to put key material in Vault). Idempotent.
- [ ] T044 [US1] Integration test `backend/tests/test_widget_e2e_chat.py` — runs the quickstart-style flow: seed → exchange → chat → assert response carries Tenant A's conversation_id.

**Checkpoint**: Story 1 is fully testable. A demo tenant + a static host page on `http://localhost:8080` (added to allowlist) produces a working chat. Safety hardening of the same path lands in US2.

---

## Phase 4: User Story 2 — Platform refuses cross-tenant and disallowed-origin abuse (Priority: P1)

**Goal**: All three attacks from spec US2 fail: disallowed-origin embed, `curl` with copied widget_id + forged/stale token, valid token with foreign `tenant_id` in body. Plus: rotation invalidates outstanding tokens; rate-limit dual-gate trips correctly.

**Independent Test**: `pytest backend/tests/redteam/cross_tenant_demo.py` reports `3/3 attacks rejected`. Rate-limit tests in `test_widget_rate_limit.py` pass.

### Tests for User Story 2 ⚠️

- [ ] T045 [P] [US2] Test in `backend/tests/test_widget_origin_csp.py`: token exchange from `https://attacker.test/` (Origin header) → 403; opaque body (no leak of "origin not allowed" vs "widget not found" vs "widget disabled").
- [ ] T046 [P] [US2] Test in `backend/tests/test_widget_origin_csp.py`: `GET /widget/embed.html` for a tenant with allowlist `[origin_a, origin_b]` returns `Content-Security-Policy` with `frame-ancestors origin_a origin_b` (exact substring match).
- [ ] T047 [P] [US2] Test in `backend/tests/test_widget_session.py`: chat with (a) missing token, (b) HS256-signed token with wrong secret, (c) token whose `exp` is 120s in the past → 401 in all cases.
- [ ] T048 [P] [US2] Test in `backend/tests/test_widget_chat.py`: POST chat with a Tenant A token AND `{"tenant_id": "<Tenant B uuid>", "message": "hi"}` → response is served under Tenant A's RLS context. Assert no Tenant B row is read; assert the body field is logged as `body_tenant_id_ignored`.
- [ ] T049 [P] [US2] Test in `backend/tests/test_widget_key_rotation.py`: issue token v1; rotate; previous token returns 401 on next chat call; a re-exchange after rotation succeeds.
- [ ] T050 [P] [US2] Test in `backend/tests/test_widget_rate_limit.py`: hammer `/api/v1/widget/session` from one IP past `WIDGET_RATE_LIMIT_PER_IP_PER_MIN` → 429 with `Retry-After`.
- [ ] T051 [P] [US2] Test in `backend/tests/test_widget_rate_limit.py`: hammer the same endpoint from many IPs against one tenant past `WIDGET_RATE_LIMIT_PER_TENANT_PER_MIN` → 429.
- [ ] T052 [P] [US2] Test in `backend/tests/test_widget_rate_limit.py`: exhausting per-IP for IP_A does NOT consume the per-tenant budget for IP_B's same-tenant traffic (separate counters).
- [ ] T053 [P] [US2] Test in `backend/tests/test_widget_loader.py`: a host page including the snippet without `data-widget-id` triggers a `console.error` and injects nothing (verified by parsing built `widget.js` AST or running the function in a jsdom).

### Implementation for User Story 2

- [ ] T054 [US2] Harden `backend/app/services/widget_session_service.py`: server-side origin check vs `allowed_origin_repo.exists_for_tenant`; widget-status check; uniform 403 response body when ANY of {bad origin, widget disabled, widget not found} fails. Verifies `Origin` header is present and well-formed.
- [ ] T055 [US2] Emit per-tenant `Content-Security-Policy: frame-ancestors …` and legacy `X-Frame-Options` headers in `backend/app/api/routes/widget_loader.py` `GET /widget/embed.html` based on the tenant's allowlist (resolved via the lookup function from T015).
- [ ] T056 [US2] Wire two-dimensional rate limit into `backend/app/api/routes/widget_session.py`: call `rate_limit.check_and_consume("ip", client_ip, …)` AND `rate_limit.check_and_consume("tenant", tenant_id, …)` on every request; 429 + `Retry-After` if either trips.
- [ ] T057 [US2] Structured logging in `backend/app/core/rate_limit.py`: on trip, log `{event: "rate_limit_trip", dimension, tenant_id_hash, count, limit}` — `tenant_id_hash` is HMAC-SHA256(tenant_id) so logs don't leak raw tenant identifiers across operators (FR-015c). Response body MUST NOT include the tripped dimension.
- [ ] T058 [US2] Implement `backend/app/services/widget_admin_service.py::rotate_signing_key(tenant_id, actor_user_id)`: marks the active row inactive (Postgres TX), writes new material to Vault (T013), inserts new row `is_active=true, version=current+1`. Rolls back the Postgres TX on Vault failure. Returns only `(version, created_at)`.
- [ ] T059 [US2] In `backend/app/api/deps.py::get_widget_session` (extended): after decoding the JWT, fetch `widget_signing_key_versions` row for `tenant_id` where `is_active=true`; if `claims.kvr != active.version`, reject 401. Caches active version per tenant for 60s alongside the key material.
- [ ] T060 [US2] Implement loader fail-closed path in `widget/src/loader.ts`: if `data-widget-id` is missing or fails regex, `console.error("[albert-widget] data-widget-id is missing or invalid")` and return — no iframe element created.
- [ ] T061 [US2] Cross-tenant red-team script `backend/tests/redteam/cross_tenant_demo.py`: implements the 3 attacks from spec US2 against a running stack and asserts each is rejected. Importable from quickstart step 8.

**Checkpoint**: Both P1 stories pass. US1 + US2 together = a shippable widget + safety guarantees. CI smoke + cross-tenant gate (built in US4) can now run against this surface.

---

## Phase 5: User Story 3 — Tenant admin self-service (Priority: P2)

**Goal**: A tenant admin can list/edit their widgets, manage their allowlist, edit guardrail config (floor-enforced), copy the embed snippet, and rotate the signing key — all via Streamlit, with no engineer assistance.

**Independent Test**: Log in to `http://localhost:8501` as `admin-acme@example.com`, change the greeting, reload the embed on the host page, observe the new greeting. Try to weaken `pii_redaction.enabled`; the admin app refuses with a floor-violation message.

### Tests for User Story 3 ⚠️

- [ ] T062 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `GET /api/v1/admin/widgets` as Tenant A admin returns only Tenant A widgets; never Tenant B's (verified by seeding both tenants).
- [ ] T063 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `PATCH /api/v1/admin/widgets/{id}` updates `theme` + `greeting` + `status`; subsequent `GET /widget/embed.html` reflects new values on next request.
- [ ] T064 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `GET /api/v1/admin/widgets/{id}/embed-snippet` returns a single `<script>` line containing the loader URL and exact `data-widget-id` — no manual editing required.
- [ ] T065 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `POST /api/v1/admin/allowed-origins` rejects (422) any of: wildcard origin (`https://*.x.com`), origin with path (`https://x.com/foo`), origin with query, origin with trailing slash, `http://example.com` (non-localhost http).
- [ ] T066 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `PUT /api/v1/admin/guardrail-config` with a config that disables `pii_redaction` → 422 with body `{error: "floor_violation", key_path: "pii_redaction.enabled", attempted_value: false, floor_value: true}`.
- [ ] T067 [P] [US3] Test in `backend/tests/test_widget_admin.py`: `POST /api/v1/admin/signing-key/rotate` returns only `{version, created_at}`; raw key material is NOT in the response body and NOT in the log stream (assert via captured logs).

### Implementation for User Story 3

- [ ] T068 [US3] Extend `backend/app/services/widget_admin_service.py`: `list_widgets`, `create_widget`, `update_widget`, `embed_snippet`, `list_allowed_origins`, `add_allowed_origin` (calls origin validator), `delete_allowed_origin`, `get_guardrail_config`, `put_guardrail_config` (calls `guardrail_floor.enforce_floor`). All methods take `actor_user_id` and derive `tenant_id` from membership lookup — never from a body field.
- [ ] T069 [US3] Implement route `backend/app/api/routes/admin_widgets.py` per `contracts/widget-admin.openapi.yaml`. Requires `current_user` with a `tenant_admin` membership for the inferred tenant. On a 4xx, returns 404 (not 403) when the resource exists but isn't owned (do not confirm existence).
- [ ] T070 [P] [US3] Streamlit auth helper `admin/app/lib/auth.py`: login form, calls `POST /api/v1/auth/login`, stores `{token, expires_at}` in `st.session_state`, logout button. Token never persisted.
- [ ] T071 [P] [US3] Backend client `admin/app/clients/backend_client.py`: thin httpx wrapper with `Authorization: Bearer …` injection and typed return shapes mirroring T025.
- [ ] T072 [P] [US3] Streamlit entry `admin/app/main.py`: `st.set_page_config`, sidebar nav, redirect to login if no token.
- [ ] T073 [P] [US3] Page `admin/app/pages/1_Widgets.py`: list, create, edit name/theme/greeting/status.
- [ ] T074 [P] [US3] Page `admin/app/pages/2_Allowed_Origins.py`: list, add (form validation mirroring T065), delete.
- [ ] T075 [P] [US3] Page `admin/app/pages/3_Guardrails.py`: render current config, accept edits, render server-side floor-violation message inline on 422.
- [ ] T076 [P] [US3] Page `admin/app/pages/4_Embed_Snippet.py`: per-widget snippet display + `st.code(..., language="html")` for copy, "Copy to clipboard" via `st.components.v1.html` shim.
- [ ] T077 [P] [US3] Page `admin/app/pages/5_Signing_Key.py`: shows current version + created_at; "Rotate" button behind a confirmation modal that names the consequence ("will sign every visitor out of every widget"). Calls `POST /api/v1/admin/signing-key/rotate`.
- [ ] T078 [P] [US3] Streamlit-side unit tests `admin/tests/test_backend_client.py`: mock httpx; assert Authorization header injection, 401 surfaced as a typed exception.
- [ ] T079 [US3] Verify `admin/Dockerfile` is lean: no `torch`, `transformers`, or `playwright`. `docker compose up admin` healthcheck green.

**Checkpoint**: A tenant admin can do the full quickstart steps 1–9 without engineer help. SC-001 demonstrably hits ≤ 10 minutes.

---

## Phase 6: User Story 4 — CI blocks merges that would silently degrade the agent (Priority: P2)

**Goal**: Every push/PR runs lint → typecheck + image-build (parallel) → smoke → 5 eval gates (parallel: classifier, agent_tool_selection, rag, redteam_cross_tenant, redaction). A regression below threshold fails the build and names the gate. Smoke failure short-circuits eval gates. No silent retries.

**Independent Test**: Open a throwaway PR that deletes a row from `evals/redteam_cross_tenant/fixtures/expected_failures.json`. CI fails on `redteam_cross_tenant` with `OBSERVED=…  THRESHOLD=1.0` in the summary. Revert → green.

### Tests / Implementation for User Story 4

- [ ] T080 [P] [US4] Classifier gate `evals/classifier/run.py` + placeholder fixtures under `evals/classifier/fixtures/`. Loads `classifier.macro_f1_min` from T008; computes macro-F1 on the fixture; prints `GATE=classifier STATUS=<…> OBSERVED=<…> THRESHOLD=<…>`; exits 0/1/2 per `contracts/ci-gate.contract.md`. Placeholder fixture produces ~0.65 to pass the default 0.60 threshold.
- [ ] T081 [P] [US4] Agent tool-selection gate `evals/tool_selection/run.py` + fixtures. Reads `agent_tool_selection.accuracy_min`. Placeholder set is 5 cases with the obvious-correct tool listed; passes 0.70 default.
- [ ] T082 [P] [US4] RAG gate `evals/rag/run.py` + fixtures. Reads `rag.hit_at_5_min` AND `rag.mrr_min`. Placeholder fixture set with deterministic top-k.
- [ ] T083 [P] [US4] Cross-tenant red-team gate `evals/redteam_cross_tenant/run.py` + `expected_failures.json` (3 attempts from spec US2). MUST achieve 1.00 to pass. Each attempt runs against a `httpx` client pointed at the in-CI backend.
- [ ] T084 [P] [US4] Redaction gate `evals/redaction/run.py` + planted-secret fixtures (`evals/redaction/fixtures/`). Asserts the planted fake key never appears in any captured response, log line, or stored trace. MUST be 1.00.
- [ ] T085 [P] [US4] Smoke test `scripts/smoke_test.sh`: `docker compose up -d`, polls `/health` on backend (8000), modelserver (8020), guardrails (8010) with timeout; tears down on exit. Exits non-zero on any failure.
- [ ] T086 [US4] Rewrite `.github/workflows/ci.yml` — PROTECTED FILE WARN. Jobs: `lint`, `typecheck`, `image_build` (parallel); `smoke` (needs `image_build`); 5 eval-gate jobs (need `smoke`, run parallel); `summary` (`needs: [classifier, tool_selection, rag, redteam, redaction]; if: always()`). NEVER uses `continue-on-error: true` for a gate (FR-030).
- [ ] T087 [US4] CI summary step in the `summary` job: reads `artifacts/ci-gate-results.jsonl` from each gate's upload, writes a markdown table to `$GITHUB_STEP_SUMMARY`, sets the check title to the first failed gate name with observed vs threshold (FR-029).
- [ ] T088 [US4] Bundle-size CI step inside the `image_build` job (or a new `widget_build` job that the bundle-size step depends on): runs `node widget/esbuild.config.mjs`, then fails if `widget/dist/widget.js > 4096 bytes` OR `widget/dist/bundle-*.js > 112640 bytes`.
- [ ] T089 [US4] Threshold-floor lint: `evals/common/validate_thresholds.py` runs as the FIRST CI step. Refuses any value of `redteam.required_pass_rate` or `redaction.required_pass_rate` < 1.0 (FR-026, FR-027).
- [ ] T090 [US4] Update `eval_thresholds.yaml`: keep current placeholder values, add a `# DAY 1 PLACEHOLDER — raise when real dataset lands` comment above each non-1.0 value, confirm `redteam.required_pass_rate: 1.00` and `redaction.required_pass_rate: 1.00` are exact.

**Checkpoint**: CI runs all six checks (lint, typecheck, image_build, smoke, 5 eval gates) on every push/PR; failures name the gate and observed-vs-threshold. SC-002, SC-006 demonstrable.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T091 [P] Update `README.md`: add a "Widget" section pointing at `specs/001-widget-auth-admin-cicd/quickstart.md`; document the new admin port (8501) in the Service Ports table.
- [ ] T092 [P] Add a short "Protected files touched" block to the PR description for this branch listing `.env.example`, `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`, `backend/app/core/config.py`, `backend/app/core/security.py`, `backend/app/db/session.py` (none expected), and `backend/alembic/versions/0003_widget_tables.py`.
- [ ] T093 Run `specs/001-widget-auth-admin-cicd/quickstart.md` end-to-end against a fresh `docker compose up --build`; capture any gaps as follow-up issues; check off Edge Cases from `spec.md` (iframe-in-iframe, zero allowed origins, token replay after origin change, clock skew, cached bundle, loader without `data-widget-id`).
- [ ] T094 [P] Re-evaluate Constitution Check post-implementation (record in `plan.md` under a new "Post-implementation Constitution Check" subsection if any drift surfaced).
- [ ] T095 [P] Tighten any placeholder eval threshold whose backing dataset has landed (coordinate with Owners A/B/C; raise in same PR that lands the data).

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
