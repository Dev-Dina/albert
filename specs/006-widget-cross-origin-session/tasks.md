---
description: "Task list for Widget Cross-Origin Session & Chat Fix"
---

# Tasks: Widget Cross-Origin Session & Chat Fix

**Input**: Design documents from `specs/006-widget-cross-origin-session/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: INCLUDED — the spec explicitly requires test changes (FR-012, SC-004)
and the constitution requires tests for changed behavior (Principle IV). Because
this is a *behavior change*, "test-first" means writing/adjusting the assertions
so they FAIL against current code, then making the change so they pass.

**Organization**: By user story (from spec.md). This fix is a single small
backend diff, so US1 carries the core change (the MVP); US2 adds the
abuse-prevention removal + isolation tests; US3 is revocation tests; US4 is the
data revert + demo.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: different file, no dependency on an incomplete task → parallelizable
- **[Story]**: US1 / US2 / US3 / US4

⚠️ **Protected/sensitive files** (warn before editing — see plan.md Constitution
Check): `backend/app/api/deps.py`, `backend/app/services/widget_session_service.py`,
`backend/app/api/middleware/widget_cors.py` (deleted), `backend/app/main.py`.

---

## Phase 1: Setup & Baseline

**Purpose**: Confirm the starting state before changing behavior.

- [X] T001 Verify the stack is healthy (`docker compose ps` → all healthy) and capture a baseline by running the widget suite `docker compose exec backend pytest tests/test_widget_session.py tests/test_widget_e2e_chat.py tests/test_widget_origin_csp.py tests/test_widget_cors.py tests/test_widget_rate_limit.py tests/test_widget_loader.py -q`; record which tests currently pass (so regressions are distinguishable from intended changes).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None required. This fix has no shared scaffolding — each user story
carries its own change. US1's backend change is the only cross-story dependency
(US3 builds on it) and is tracked as such in Dependencies below.

*(Intentionally empty — proceed to Phase 3.)*

---

## Phase 3: User Story 1 - Visitor on an allowlisted customer site can chat (Priority: P1) 🎯 MVP

**Goal**: A real cross-origin embed (iframe served from the backend origin) can
exchange a session and chat. This is the core bug fix.

**Independent Test**: POST `/session` and `/chat` with `Origin` == the backend
origin (the value a real browser sends from the backend-served iframe) and an
enabled widget; both succeed. Previously 403/401.

### Tests for User Story 1 (write first; they FAIL against current code)

- [X] T002 [P] [US1] In `backend/tests/test_widget_session.py` add a test that POSTs `/api/v1/widget/session` with header `Origin: http://localhost:8000` (the backend origin, NOT an allowlisted customer origin) for an enabled widget and asserts **200** + a `session_token` (contract C-S1). Confirm it fails today (currently 403). In the same file, also add/keep an assertion that a POST with **no** `Origin` header still returns **400** (FR-009 fail-closed, retained under Approach A).
- [X] T003 [P] [US1] In `backend/tests/test_widget_e2e_chat.py` add a test that POSTs `/api/v1/widget/chat` with a valid token and `Origin: http://localhost:8000`, and a second variant with **no** `Origin` header, asserting **200** in both (contract C-C1).

### Implementation for User Story 1

- [X] T004 [US1] In `backend/app/services/widget_session_service.py` `exchange()`, remove the customer-allowlist check (the `allowed = await allowed_origin_repo.exists_for_tenant(...)` call and the `if not allowed: raise WidgetSessionError("origin not allowed")`). Keep `_origin_well_formed()`, the widget-status check, the signing-key resolution, and the `tenant_context`. Update the module docstring to drop the "well-formed-Origin check ... origin not allowed" allowlist claim and describe Approach A. (makes T002 pass)
- [X] T005 [US1] In `backend/app/api/deps.py` `get_widget_session()`, remove the entire Origin re-check block (the `origin = request.headers.get("origin")`, the `if not origin: raise ...`, the `allowed_origin_repo.exists_for_tenant(...)` call, and the `if not origin_ok: raise ...`), plus the now-unused `from app.repositories import allowed_origin_repo` import and the "Origin re-check (T059a / SC-008)" docstring paragraph. Keep token verification, key-version check, Vault key load, and `tenant_context`. (makes T003 pass)
- [X] T006 [US1] Re-run T002, T003 and the existing `test_widget_session.py` chat-401 group; confirm the new tests pass and the 401-on-bad-token tests still pass.

**Checkpoint**: Cross-origin embeds now work end-to-end (MVP). Tenant identity is still token-derived; isolation untouched.

---

## Phase 4: User Story 2 - Embedding off-allowlist refused; isolation & abuse limits hold (Priority: P1)

**Goal**: Removing the per-tenant CORS ACAO emission so a non-allowlisted site
cannot drive a tenant's widget in-browser, while cross-tenant isolation,
anti-enumeration, and rate limits remain intact.

**Independent Test**: A cross-origin browser caller gets no `Access-Control-Allow-Origin`
header (so it cannot read responses); `frame-ancestors` still blocks framing; a
token for Tenant A never acts as Tenant B; unknown/disabled widget still returns
a uniform 403; rate limits still return 429.

### Tests for User Story 2 (write first)

- [X] T007 [P] [US2] Replace `backend/tests/test_widget_cors.py`: remove the ACAO-echo and 403-on-disallowed-origin assertions; add assertions that a POST to `/api/v1/widget/session` carries **no** `Access-Control-Allow-Origin` header, and that an `OPTIONS` preflight to `/api/v1/widget/chat` is not granted an ACAO echoing the caller's origin (no widget CORS handler remains).
- [X] T008 [P] [US2] In `backend/tests/test_widget_origin_csp.py`, repurpose `test_token_exchange_from_attacker_origin_returns_403_opaque_body` to assert a non-allowlisted origin now **succeeds (200)** at `/session` (C-S1); KEEP `test_token_exchange_for_unknown_widget_returns_same_opaque_403` (C-S2) and `test_embed_html_emits_per_tenant_frame_ancestors` (T046) unchanged.
- [X] T009 [P] [US2] Review `backend/tests/redteam/cross_tenant_demo.py`: ensure it still asserts cross-tenant refusal/no-leak under Approach A; adjust ONLY if it depended on the removed origin rejection (not on token isolation).

### Implementation for User Story 2

- [X] T010 [US2] Remove the per-tenant CORS middleware: delete `backend/app/api/middleware/widget_cors.py`, and in `backend/app/main.py` remove `from app.api.middleware.widget_cors import WidgetCorsMiddleware` and the `app.add_middleware(WidgetCorsMiddleware)` line. (makes T007 pass)
- [X] T011 [US2] Re-run T007, T008, T009 plus `tests/test_widget_rate_limit.py`; confirm cross-origin reads are blocked, anti-enumeration 403 holds, isolation holds, and rate limits still return 429.

**Checkpoint**: US1 + US2 both verified — embeds work, and the public surface is bounded exactly by frame-ancestors + token isolation + rate limits.

---

## Phase 5: User Story 3 - Admin allowlist changes / TTL-bounded revocation (Priority: P2)

**Goal**: Confirm the new revocation semantics: removing an origin blocks new
embeds immediately (frame-ancestors), while an already-issued token keeps
working until it expires.

**Independent Test**: With the origin removed from the allowlist, a valid
unexpired token still returns 200 on `/chat`; `embed.html` no longer lists the
removed origin in `frame-ancestors`.

**Depends on**: US1 (the `/chat` origin re-check must already be removed).

### Tests for User Story 3 (write first)

- [X] T012 [P] [US3] In `backend/tests/test_widget_origin_csp.py`, rewrite `test_chat_rejects_token_after_origin_removed_from_allowlist` (T059b) to assert chat returns **200** with a valid unexpired token after the origin is removed (contract C-C3, TTL-bounded revocation); rename it to reflect the new behavior (e.g. `test_chat_still_succeeds_after_origin_removed_until_token_expiry`).
- [X] T013 [P] [US3] In `backend/tests/test_widget_origin_csp.py`, simplify `test_chat_succeeds_when_origin_still_on_allowlist` to assert a valid token → **200** independent of the allowlist; verify `test_embed_html_emits_per_tenant_frame_ancestors` (T046) still passes as the embedding control.

### Implementation for User Story 3

- [X] T014 [US3] Run `tests/test_widget_origin_csp.py` and `tests/test_widget_loader.py`; confirm green. (No production-code change beyond US1 — this story is verified by tests of behavior US1/US2 already deliver.)

**Checkpoint**: Revocation semantics confirmed and documented in tests.

---

## Phase 6: User Story 4 - Remove the temporary local-demo hack (Priority: P3)

**Goal**: Delete the manually-added `http://localhost:8000` allowlist row and
confirm the demo works through the corrected flow.

**Independent Test**: After deleting the `:8000` row, the demo at
`http://localhost:8080` still frames the widget and chats.

**Depends on**: US1 (so the demo's same-origin `/session` succeeds without the hack).

- [X] T015 [US4] Revert the hack per quickstart §1: `docker compose exec postgres psql -U albert_app -d albert -c "DELETE FROM widget_allowed_origins WHERE origin = 'http://localhost:8000';"` then verify only the real demo origin (`http://localhost:8080`) and any real customer origins remain.
- [X] T016 [US4] Run the local demo per quickstart §2 (serve `scripts/demo_host` on `:8080`, open it): confirm the chat bubble frames, DevTools shows `POST /session` returning **200** with request `Origin: http://localhost:8000`, and a message round-trips — all without the `:8000` allowlist entry.

**Checkpoint**: The workaround is gone and the corrected flow is proven locally.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T017 [P] Search for stale references to the removed origin checks / old FR labels in code comments and docstrings (`backend/app/api/deps.py`, `backend/app/services/widget_session_service.py`, `backend/app/api/routes/widget_session.py`) and update them to describe Approach A (allowlist = embedding control only).
- [X] T018 [P] Check whether `allowed_origin_repo.exists_for_tenant` is still referenced anywhere after T004/T005; if it is now unused, either remove it or leave a one-line note that it is retained for future use (no behavior change). File: `backend/app/repositories/allowed_origin_repo.py`.
- [X] T019 Run the full backend suite `docker compose exec backend pytest -q` and confirm no collateral breakage outside the intentionally-changed widget tests.
- [X] T020 Execute `specs/006-widget-cross-origin-session/quickstart.md` steps 1–6 and confirm SC-001 through SC-006 (cross-origin chat works, off-allowlist framing blocked, isolation holds, demo works post-revert).

---

## Dependencies & Execution Order

### Phase / Story dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: empty by design.
- **US1 (Phase 3)** 🎯 MVP: no dependency on other stories; carries the core diff.
- **US2 (Phase 4)**: independent of US1 for its OWN assertions (US1's happy path passes whether or not the middleware is removed), but should be merged together as one PR; T010 (middleware removal) is what its tests need.
- **US3 (Phase 5)**: **depends on US1** (T005 removes the `/chat` origin re-check that T012 relies on).
- **US4 (Phase 6)**: **depends on US1** (demo `/session` succeeds without the hack only after T004).
- **Polish (Phase 7)**: after US1–US4.

### Within a story

- Write/adjust the test (so it fails) → make the code change → re-run.
- US1: T002,T003 (tests) → T004,T005 (code, parallel — different files) → T006 (verify).
- US2: T007,T008,T009 (tests) → T010 (code) → T011 (verify).

### Parallel opportunities

- T002 ‖ T003 (different test files).
- T004 ‖ T005 (different source files; `widget_session_service.py` vs `deps.py`).
- T007 ‖ T008 ‖ T009 (different test files).
- T012 ‖ T013 are in the same file (`test_widget_origin_csp.py`) → NOT parallel; do sequentially.
- T017 ‖ T018 (different files).

---

## Parallel Example: User Story 1

```bash
# Tests first (different files, run/author in parallel):
Task: "Add backend-origin /session success test in backend/tests/test_widget_session.py"   # T002
Task: "Add backend-origin / no-origin /chat success test in backend/tests/test_widget_e2e_chat.py"  # T003

# Then the two code edits (different files, parallel):
Task: "Remove allowlist check in backend/app/services/widget_session_service.py exchange()"  # T004
Task: "Remove Origin re-check block in backend/app/api/deps.py get_widget_session()"          # T005
```

---

## Implementation Strategy

### MVP (User Story 1 only)

1. Phase 1 setup/baseline.
2. Phase 3 (US1): the two backend edits + their tests → cross-origin embeds work.
3. **STOP & VALIDATE**: real-browser-origin session/chat succeed; bad-token 401s still hold.

### Incremental delivery (recommended single PR)

US1 → US2 → US3 → US4 → Polish, committed in that order. Because the changes are
one small, tightly-coupled diff touching tenant-isolation files, ship them as a
**single focused PR** (Constitution V) after `/speckit.analyze`, rather than
four separate merges.

---

## Notes

- [P] = different files, no incomplete-task dependency.
- This is a behavior-CHANGE feature: do not delete tests of old behavior silently — repurpose them to assert the new behavior (FR-012, Principle IV).
- No migration, no `config.py`/`security.py` edits, no frontend change.
- Commit after each story; keep `CLAUDE.md` SPECKIT edits unstaged (managed separately).
- `/speckit.analyze` is REQUIRED before `/speckit.implement` (risky feature).
