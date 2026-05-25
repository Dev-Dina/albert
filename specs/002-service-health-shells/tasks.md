---
description: "Task list for Service Health Shells"
---

# Tasks: Service Health Shells

**Input**: Design documents from `specs/002-service-health-shells/`

**Prerequisites**: plan.md (required), spec.md (required)

**Tests**: INCLUDED — the spec requests automated tests per service (FR-008, SC-003).

**Organization**: Tasks are grouped by user story. The three services are fully independent, so
each story is a self-contained vertical slice that can be built and tested on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = backend, US2 = modelserver, US3 = guardrails
- All paths are relative to the repository root.

## Path Conventions

- Three independent Python packages: `backend/`, `modelserver/`, `guardrails/`, each with its own
  `pyproject.toml` (uv-managed) and `tests/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization shared across services.

- None. The three services are fully independent; each is scaffolded inside its own user-story
  phase. No shared code or config exists this phase.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Cross-cutting prerequisites that block all stories.

- None required. No shared base models, auth, DB, or middleware this phase (all out of scope).

---

## Phase 3: User Story 1 - Backend health (Priority: P1) 🎯 MVP

**Goal**: A runnable `backend` FastAPI service answering `GET /health` with its identity payload.

**Independent Test**: Start only `backend`, call `GET /health`, confirm
`{"status":"ok","service":"backend","app":"albert"}`.

- [X] T001 [P] [US1] Create `backend/pyproject.toml` — Python 3.12, uv; deps: `fastapi`, `uvicorn`, `pydantic-settings`; dev deps: `pytest`, `httpx`, `ruff`. No other dependencies.
- [X] T002 [US1] Create backend package markers: `backend/app/__init__.py`, `backend/app/api/__init__.py`, `backend/app/api/routes/__init__.py`, `backend/app/core/__init__.py`
- [X] T003 [US1] Create `backend/app/core/config.py` — `pydantic-settings` `Settings` with `app_name="albert"`, `service_name="backend"`; expose a `settings` instance
- [X] T004 [US1] Create `backend/tests/test_health.py` — `TestClient` asserts `GET /health` returns 200 and `{"status":"ok","service":"backend","app":"albert"}` (run first; expect fail)
- [X] T005 [US1] Create `backend/app/api/routes/health.py` — `APIRouter` with `async def` `GET /health` returning `{"status":"ok","service":settings.service_name,"app":settings.app_name}`
- [X] T006 [US1] Create `backend/app/main.py` — construct `FastAPI()` app and include the health router
- [ ] T007 [US1] Run `backend` checks: `uv run pytest` and `uv run ruff check .` — confirm test passes and lint is clean

**Checkpoint**: Backend runs and passes its health test independently (MVP).

---

## Phase 4: User Story 2 - Modelserver health + predict placeholder (Priority: P2)

**Goal**: A runnable `modelserver` service with `GET /health` and a placeholder `POST /predict`.

**Independent Test**: Start only `modelserver`, call `GET /health` and `POST /predict`, confirm
documented payloads.

- [X] T008 [P] [US2] Create `modelserver/pyproject.toml` — Python 3.12, uv; deps: `fastapi`, `uvicorn`; dev deps: `pytest`, `httpx`, `ruff`. No other dependencies.
- [X] T009 [US2] Create `modelserver/app/__init__.py` (package marker)
- [X] T010 [US2] Create `modelserver/tests/test_health.py` — `TestClient` asserts `GET /health` → `{"status":"ok","service":"modelserver","app":"albert"}` and `POST /predict` → `{"label":"unknown","confidence":0.0}` (run first; expect fail)
- [X] T011 [US2] Create `modelserver/app/main.py` — `FastAPI()` app with `async` `GET /health` (identity payload) and `async` `POST /predict` returning the fixed placeholder; ignore request body
- [ ] T012 [US2] Run `modelserver` checks: `uv run pytest` and `uv run ruff check .` — confirm pass + clean lint

**Checkpoint**: Modelserver runs and passes its tests independently.

---

## Phase 5: User Story 3 - Guardrails health + check placeholders (Priority: P3)

**Goal**: A runnable `guardrails` service with `GET /health`, `POST /check-input`, and
`POST /check-output` placeholders.

**Independent Test**: Start only `guardrails`, call all three endpoints, confirm documented
payloads.

- [X] T013 [P] [US3] Create `guardrails/pyproject.toml` — Python 3.12, uv; deps: `fastapi`, `uvicorn`; dev deps: `pytest`, `httpx`, `ruff`. No other dependencies.
- [X] T014 [US3] Create `guardrails/app/__init__.py` (package marker)
- [X] T015 [US3] Create `guardrails/tests/test_health.py` — `TestClient` asserts `GET /health` → identity payload, `POST /check-input` and `POST /check-output` → `{"allowed":true,"reason":"phase_1_placeholder"}` (run first; expect fail)
- [X] T016 [US3] Create `guardrails/app/main.py` — `FastAPI()` app with `async` `GET /health` (identity payload), `async` `POST /check-input` and `async` `POST /check-output` returning the fixed placeholder; ignore request body
- [ ] T017 [US3] Run `guardrails` checks: `uv run pytest` and `uv run ruff check .` — confirm pass + clean lint

**Checkpoint**: All three services run and pass their tests independently.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T018 [P] Verify constitution compliance across all three services: endpoints are `async`, no `print`, no secrets, and no out-of-scope dependencies (no Docker/auth/DB/Vault/Redis/MinIO/RAG/agent/widget) in any `pyproject.toml`

---

## Dependencies & Execution Order

- **Phase 1 / Phase 2**: empty — user stories can start immediately.
- **US1, US2, US3**: independent of each other; may proceed in parallel or in priority order.
- **Within each story**: `pyproject.toml` → package markers → test (red) → implementation (green)
  → run checks. `main.py` depends on its config/router (US1) being present.
- **Phase 6**: after the desired stories are complete.

## Parallel Opportunities

- T001, T008, T013 (the three `pyproject.toml` files) can run in parallel.
- The three stories can be developed in parallel by different people — no shared files.

## Implementation Strategy

- **MVP**: Phase 3 (US1 backend) alone — smallest demonstrable slice.
- **Incremental**: add US2, then US3; each is an independent, testable increment.

## Notes

- **Deferred (NOT in this task list, per plan)**: README run instructions and a Makefile
  run/test target. Do not edit them this phase.
- Tenant-isolation note: the `POST` placeholders (`/predict`, `/check-input`, `/check-output`)
  ignore their request body and MUST NOT introduce any `tenant_id`-from-body handling — that is
  the surface where Constitution Principle I will apply in later phases.
