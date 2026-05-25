# Implementation Plan: Service Health Shells

**Branch**: `main` | **Date**: 2026-05-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-service-health-shells/spec.md`

## Summary

Build three independent, minimal FastAPI service shells — `backend`, `modelserver`, and
`guardrails`. Each exposes an async `GET /health` returning a fixed identity payload.
`modelserver` adds an async `POST /predict` placeholder; `guardrails` adds async
`POST /check-input` and `POST /check-output` placeholders. Each service is its own Python
package with its own `pyproject.toml`, and each ships minimal endpoint tests. No real logic,
no infrastructure — placeholders only.

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: FastAPI, uvicorn (run). `backend` only: pydantic-settings for minimal
config. Dev/test: pytest, FastAPI `TestClient` (httpx-backed), ruff.

**Storage**: N/A (no database this phase)

**Testing**: pytest using FastAPI `TestClient`

**Target Platform**: Local / Linux server via uvicorn

**Project Type**: Web service — three independent FastAPI apps

**Performance Goals**: Health responds < 500 ms locally when idle (SC-005)

**Constraints**: Each service independent with its own `pyproject.toml`; async endpoints; tiny
files; no unnecessary dependencies; no secrets; logging not `print`; no Docker/Compose; no
auth/DB/Vault/Redis/MinIO/RAG/agent/widget/Streamlit.

**Scale/Scope**: 3 services, 5 endpoints total, placeholder responses only.

**Package manager**: uv (per-service).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Tenant Isolation (NON-NEGOTIABLE) | ✅ PASS | No tenant data, DB, RAG, or `tenant_id` inputs this phase. Placeholders MUST NOT read any `tenant_id` from request bodies. |
| II. Layered Architecture & Async | ✅ PASS | `backend` splits routes (`api/routes/health.py`) from config (`core/config.py`); all endpoints async. `modelserver`/`guardrails` are single-file `main.py` given trivial scope. |
| III. Security & Secrets Hygiene (NON-NEGOTIABLE) | ✅ PASS | No secrets, no `.env` committed, logging not `print`. |
| IV. Test Integrity for Changed Behavior | ✅ PASS | Each service ships tests covering every endpoint it exposes. |
| V. Spec-Driven, Phased Delivery | ✅ PASS | Simple (non-risky) feature; not building ahead of phase. Working directly on `main` per explicit user instruction for this task. |

No violations. Complexity Tracking not required.

## Project Structure

### Documentation (this feature)

```text
specs/002-service-health-shells/
├── spec.md              # Feature spec (complete)
├── plan.md              # This file
├── checklists/
│   └── requirements.md  # Spec quality checklist (passing)
└── tasks.md             # Created later by /speckit-tasks
```

(No `research.md` / `data-model.md` / `contracts/` generated: the stack is fully specified and
response shapes are fixed in the spec, so there are no unknowns to research or entities to model.)

### Source Code (repository root)

```text
backend/
├── pyproject.toml            # FastAPI, uvicorn, pydantic-settings; dev: pytest, httpx, ruff
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI app, includes health router
│   ├── api/
│   │   └── routes/
│   │       └── health.py     # async GET /health -> {status, service:"backend", app:"albert"}
│   └── core/
│       └── config.py         # pydantic-settings: app name + service name
└── tests/
    └── test_health.py        # asserts /health payload

modelserver/
├── pyproject.toml            # FastAPI, uvicorn; dev: pytest, httpx, ruff
├── app/
│   ├── __init__.py
│   └── main.py               # async GET /health + async POST /predict placeholder
└── tests/
    └── test_health.py        # asserts /health and /predict payloads

guardrails/
├── pyproject.toml            # FastAPI, uvicorn; dev: pytest, httpx, ruff
├── app/
│   ├── __init__.py
│   └── main.py               # async GET /health + POST /check-input + POST /check-output
└── tests/
    └── test_health.py        # asserts /health, /check-input, /check-output payloads
```

**Structure Decision**: Three independent Python packages, each with its own `pyproject.toml`
managed by uv, so any service runs and tests in isolation (FR-007). `backend` uses the project's
layered split (routes + core config) since it is the central service and will grow; `modelserver`
and `guardrails` stay single-file `main.py` because their placeholder scope does not justify
extra layers yet (no unnecessary structure).

**Endpoint contracts** (from spec, fixed this phase):

| Service | Method/Path | Response |
|---------|-------------|----------|
| backend | `GET /health` | `{"status":"ok","service":"backend","app":"albert"}` |
| modelserver | `GET /health` | `{"status":"ok","service":"modelserver","app":"albert"}` |
| modelserver | `POST /predict` | `{"label":"unknown","confidence":0.0}` |
| guardrails | `GET /health` | `{"status":"ok","service":"guardrails","app":"albert"}` |
| guardrails | `POST /check-input` | `{"allowed":true,"reason":"phase_1_placeholder"}` |
| guardrails | `POST /check-output` | `{"allowed":true,"reason":"phase_1_placeholder"}` |

**Deferred (planned, not edited this phase)**: README run instructions and a Makefile target to
launch/test the three services may be added later; not touched now.

## Complexity Tracking

> No constitution violations. Section intentionally empty.
