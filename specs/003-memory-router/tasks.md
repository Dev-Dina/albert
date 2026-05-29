# Tasks: Memory and Router

**Input**: Design documents from `specs/003-memory-router/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add new dependencies and wire new adapters into lifespan

- [x] T001 Add `redis[asyncio]` to `backend/pyproject.toml` dependencies
- [x] T002 Add `redis_session_ttl: int = 1800` and `router_confidence_threshold: float = 0.7` to `backend/app/core/config.py` (PROTECTED — warn before editing)
- [x] T003 Update `backend/app/lifespan.py` to build async Redis client at startup and mount on `app.state.redis`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core schemas and request/response models that all user story phases depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Create `backend/app/schemas/chat.py` — `ChatRequest` (conversation_id: str, message: str) and `ChatResponse` (reply: str, routed_to: Literal["router", "agent"]) Pydantic models
- [x] T005 [P] Create `backend/app/schemas/router.py` — `RouterDecision` dataclass with fields: `action: Literal["agent", "direct"]`, `reply: str | None`, `label: str`, `confidence: float`, `routed_to: str`

**Checkpoint**: Foundation ready — user story phases can now begin

---

## Phase 3: User Story 1 — Visitor receives a contextually-aware response (Priority: P1) 🎯 MVP

**Goal**: Conversation turns are stored per-tenant per-conversation in Redis with TTL; each new message loads prior context so the agent can reference it.

**Independent Test**: Start a two-turn conversation using `POST /chat`, verify the second reply reflects context from the first turn; then wait for TTL expiry and verify the session is gone.

### Implementation

- [x] T006 [US1] Create `backend/app/services/memory.py` — `MemoryService` with `load_history(tenant_id, conversation_id) -> list[dict]` and `save_turn(tenant_id, conversation_id, user_message, assistant_reply) -> None`; key format `conv:{tenant_id}:{conversation_id}`; max 10 turns; TTL from `settings.redis_session_ttl`; `_redact(text) -> str` stub; graceful Redis error handling
- [x] T007 [US1] Create `backend/tests/test_memory.py` — 5 unit tests: load returns empty on miss, save+load roundtrip, max-10-turn cap, TTL reset on write, cross-tenant key isolation

**Checkpoint**: User Story 1 complete — memory service is live and tenant-isolated ✅

---

## Phase 4: User Story 2 — Simple queries are answered without invoking the full agent (Priority: P2)

**Goal**: An HTTP classifier router classifies each message and either returns a direct canned reply or hands off to the agent; falls back to agent on any error or low confidence.

**Independent Test**: Mock the model-server `/classify` endpoint returning label=`greeting` confidence=0.9; verify `routed_to="router"` in the response and no RAG call. Then mock an HTTP error and verify `routed_to="agent"`.

### Implementation

- [x] T008 [US2] Create `backend/app/services/router.py` — `RouterService` with `classify_and_route(message, tenant_id) -> RouterDecision`; HTTP POST to `{settings.modelserver_url}/classify` with `Authorization: Bearer {service_auth_token}`; label map (`greeting`, `farewell`, `out_of_scope` → direct replies); confidence threshold check; fallback to `action="agent"` on error or low confidence; stub counter log for `router_handled` / `agent_handled`
- [x] T009 [US2] Create `backend/app/api/routes/chat.py` — `POST /chat` endpoint; tenant_id from `X-Tenant-Id` header; full flow: load history → redact → guardrails pre-check stub → router → agent if needed → guardrails post-check stub → save turn → return `ChatResponse`
- [x] T010 [US2] Register `chat_router` in `backend/app/main.py`
- [x] T011 [US2] Create `backend/tests/test_router.py` — 5 unit tests: greeting label returns direct reply, farewell returns direct reply, low confidence falls back to agent, HTTP error falls back to agent, ambiguous label falls back to agent

**Checkpoint**: User Story 2 complete — router is live and agent fallback works ✅

---

## Phase 5: User Story 3 — Team can measure tool-selection accuracy (Priority: P2)

**Goal**: A labelled eval dataset and eval script let CI verify the agent picks the right tool (or no tool) for known messages; blocks on accuracy regression.

**Independent Test**: Run `python -m evals.tool_selection_eval --golden evals/tool_selection.jsonl` — confirms it prints per-example pass/fail + overall accuracy and exits non-zero when accuracy < 0.8.

### Implementation

- [x] T012 [US3] Create `evals/tool_selection.jsonl` — 15 hand-labelled examples: 5× `rag_search` (knowledge questions), 3× `capture_lead` (contact/lead capture), 3× `escalate` (complaints, urgency), 4× `null` (direct answer, no tool needed — greetings, simple yes/no)
- [x] T013 [US3] Create `evals/tool_selection_eval.py` — CLI: loads JSONL, for each example uses a deterministic tool selector, compares to expected_tool, prints per-example PASS/FAIL + accuracy; exits non-zero if `accuracy < eval_thresholds.yaml[agent_tool_selection.accuracy_min]`
- [x] T014 [US3] Update root `eval_thresholds.yaml` — add `agent_tool_selection.accuracy_min`
- [x] T015 [US3] Update `.github/workflows/ci.yml` — add tool-selection eval steps that run `tool_selection_eval.py` and `evals.tool_selection.run`, blocking on non-zero exit

**Checkpoint**: User Story 3 complete — tool-selection eval harness is live and wired to CI ✅

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T016 [P] Write `specs/003-memory-router/memory.md` — one sentence justifying the Redis session TTL default (30 min: covers typical customer support conversation without accumulating stale data)
- [x] T017 Run full test suite in `backend/` — all tests passing including T007 and T011
- [x] T018 Run quickstart.md validation manually (requires Redis + model-server running)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1 Memory)**: Depends on Phase 2
- **Phase 4 (US2 Router + Chat)**: Depends on Phase 2; integrates Phase 3 memory service
- **Phase 5 (US3 Eval)**: Independent of US1/US2 — can run in parallel after Phase 2
- **Phase 6 (Polish)**: Depends on Phases 3, 4, 5

### Task Count Summary

| Phase | Tasks | Status |
|-------|-------|--------|
| Phase 1 — Setup | 3 | ✅ Done |
| Phase 2 — Foundational | 2 | ✅ Done |
| Phase 3 — US1 Memory | 2 | ✅ Done |
| Phase 4 — US2 Router | 4 | ✅ Done |
| Phase 5 — US3 Eval | 4 | ✅ Done |
| Phase 6 — Polish | 3 | ✅ Done |
| **Total** | **18** | **18/18** |

### Parallel Opportunities

- T004 and T005 (Phase 2) can run in parallel
- T006 (memory service) and T008 (router service) can run in parallel once Phase 2 is done
- T012 (eval JSONL) can start any time — it's just data

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 + Phase 2
2. Complete Phase 3 (memory service + tests)
3. **STOP and VALIDATE**: Two-turn conversation works, TTL expiry works, tenant isolation verified
4. Proceed to Phase 4 (router + chat endpoint)

### Incremental Delivery

1. Setup + Foundational → schemas ready
2. Memory service → contextual conversation works
3. Router + Chat endpoint → full flow wired, simple queries short-circuit
4. Eval harness → quality gate live in CI
