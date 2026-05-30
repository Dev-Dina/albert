# Implementation Plan: Widget Cross-Origin Session & Chat Fix

**Branch**: `006-widget-cross-origin-session` | **Date**: 2026-05-30 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/006-widget-cross-origin-session/spec.md`

## Summary

Real third-party widget embeds are broken: the widget bundle runs inside an
iframe served from the **backend** origin, so the browser attaches the backend
origin to `POST /api/v1/widget/session` and `POST /api/v1/widget/chat`. The
backend compares that origin against the per-tenant **customer** allowed-origins
list and refuses every genuine embed (403 on session, 401 on chat).

Per the Clarifications (Approach A), the fix **decouples the customer
allowlist from the request-time origin checks**. Tenant identity already comes
solely from the server-derived, signed widget session token; the customer
allowlist's enforcement role is narrowed to the embedding control it already
powers correctly — the per-tenant `frame-ancestors` CSP on `embed.html`. The
session and chat endpoints stop comparing the request origin against the
customer allowlist. Cross-origin in-browser abuse is held off by removing ACAO
emission (so the browser same-origin policy blocks cross-origin reads), and
abuse generally is bounded by the existing per-IP and per-tenant rate limits.

This is a **backend-only behavior change plus test updates plus a one-row data
revert**. The widget frontend already issues the correct same-origin requests;
no widget rebuild is required.

## Technical Context

**Language/Version**: Python 3.11 (backend), TypeScript/React (widget — not modified)

**Primary Dependencies**: FastAPI, Starlette middleware, SQLAlchemy (async), `python-jose` (HS256 widget tokens), Postgres + pgvector with FORCE RLS, Redis, Vault (per-tenant widget signing keys)

**Storage**: PostgreSQL. No schema change. `widget_allowed_origins` table is retained and continues to drive `frame-ancestors`.

**Testing**: pytest (`backend/tests`). Contract/unit tests with dependency overrides + a wiring-level e2e test (no live infra).

**Target Platform**: Linux server (Docker Compose), behind the backend origin that also serves the widget loader, iframe, and bundle.

**Project Type**: Web service (FastAPI backend) + embeddable browser widget.

**Performance Goals**: No new latency budget; the change removes one DB lookup per `/session` and one per `/chat` (a small net reduction).

**Constraints**: Tenant isolation is absolute (Constitution I). No secret logging (III). Changed behavior must be covered by tests (IV). Uniform-refusal (anti-enumeration) responses preserved. Session TTL (currently 900 s) remains the exposure bound for already-issued tokens after an allowlist change.

**Scale/Scope**: Touches 4 backend source files (+1 deletion), ~4 test files, 1 docs pointer, and 1 runtime data row. No migration, no config-schema change, no frontend change.

## Constitution Check

*GATE: must pass before Phase 0 and re-checked after Phase 1.*

| Principle | Assessment | Verdict |
|-----------|-----------|---------|
| I. Tenant Isolation (NON-NEGOTIABLE) | Tenant identity is derived **only** from the signed token (`tnt` claim) resolved server-side — never from the request origin or body. The removed origin checks were **never** the isolation control; isolation is enforced by token signature + RLS tenant context. Cross-tenant tests are retained/added (FR-003, US2 scenario 2). | PASS (see research.md §1 for the explicit argument) |
| II. Layered Architecture & Async | Edits stay within their layers: service (`widget_session_service`), API dependency (`deps`), route (`widget_session`), middleware (`widget_cors` removed), wiring (`main`). All async preserved. | PASS |
| III. Security & Secrets Hygiene (NON-NEGOTIABLE) | No secrets logged; no new secret handling. Removing ACAO emission is a net hardening (blocks cross-origin browser reads). | PASS |
| IV. Test Integrity for Changed Behavior | Every behavior change has a corresponding test update (see Phase 1 / contracts). Tests asserting the old origin-rejection behavior are rewritten to assert the new behavior, not deleted silently. | PASS |
| V. Spec-Driven, Phased Delivery | Full risky-feature flow in use (specify → clarify → **plan** → tasks → analyze → implement). Small, single-purpose branch off `main`. No direct push to `main`. | PASS |

**Protected / sensitive files touched** (Constitution "Security & Operational Constraints" — warn before editing):

- `backend/app/api/deps.py` — widget-token auth + tenant-context dependency (**tenant-isolation file**). ⚠️ Warn.
- `backend/app/services/widget_session_service.py` — widget token exchange (**tenant-isolation / widget-token-auth file**). ⚠️ Warn.
- `backend/app/api/middleware/widget_cors.py` — to be **removed**. ⚠️ Warn.
- `backend/app/main.py` — middleware registration removed (not on the protected list, but app-wiring; review carefully).

NOT touched: `core/config.py`, `core/security.py`, `core/logging.py`, `db/session.py`, any Alembic migration, platform prompts, `docker-compose.yml`, `Makefile`, `.github/workflows/*`. No gate violations; **Complexity Tracking not required**.

## Project Structure

### Documentation (this feature)

```text
specs/006-widget-cross-origin-session/
├── plan.md              # This file
├── spec.md              # Feature spec (with Clarifications)
├── research.md          # Phase 0 — decisions & rationale
├── data-model.md        # Phase 1 — entities (no schema change)
├── quickstart.md        # Phase 1 — how to verify the fix locally
├── contracts/
│   ├── widget-session.md   # POST /api/v1/widget/session behavior under Approach A
│   └── widget-chat.md      # POST /api/v1/widget/chat behavior under Approach A
├── checklists/
│   └── requirements.md  # Spec quality checklist (passing)
└── tasks.md             # Phase 2 — created by /speckit.tasks (NOT here)
```

### Source Code (repository root)

```text
backend/app/
├── api/
│   ├── deps.py                         # EDIT: remove the origin re-check in get_widget_session
│   ├── routes/
│   │   ├── widget_session.py           # KEEP Origin-present 400 gate (FR-009); no allowlist logic here
│   │   ├── widget_chat.py              # No change (origin handling lives in the dep)
│   │   └── widget_loader.py            # No change — frame-ancestors stays the embedding control
│   └── middleware/
│       └── widget_cors.py              # DELETE: stop echoing ACAO (prevents cross-origin browser abuse)
├── services/
│   └── widget_session_service.py       # EDIT: remove allowlist (exists_for_tenant) check in exchange()
├── repositories/
│   └── allowed_origin_repo.py          # No change (still used by frame-ancestors + admin mgmt)
└── main.py                             # EDIT: remove app.add_middleware(WidgetCorsMiddleware)

backend/tests/
├── test_widget_origin_csp.py           # EDIT: repurpose T045 attacker-origin + T059b revocation tests
├── test_widget_cors.py                 # REPLACE: assert no-ACAO / cross-origin blocked posture
├── test_widget_session.py              # ADD: real-browser-origin success (Origin == backend origin)
└── test_widget_e2e_chat.py             # ADD: chat still succeeds after origin removed (TTL-bounded)

scripts/
├── seed_demo_tenant.py                 # No change (already seeds the correct demo origin :8080)
└── demo_host/index.html                # No change (origin :8080, framed by frame-ancestors)

widget/src/                             # No change — loader/api already same-origin to backend
```

**Structure Decision**: Existing FastAPI layered backend + embeddable widget. The fix is confined to the widget session/chat request-time origin handling and its tests; the data model, migrations, config, and frontend are untouched.

### Runtime data revert (not source code)

- Delete the manually-inserted `http://localhost:8000` row from Acme's
  `widget_allowed_origins` (added as a temporary local hack). This is an
  ops/data step run against the dev database, captured in `quickstart.md` and
  as a task; it is **not** in any seed file (the seed already uses the correct
  `http://localhost:8080`).

## Complexity Tracking

No constitution violations — section intentionally empty.
