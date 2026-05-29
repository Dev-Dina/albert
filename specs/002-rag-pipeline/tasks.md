# Tasks: RAG Pipeline

**Input**: Design documents from `specs/002-rag-pipeline/`

**Prerequisites**: plan.md ✅ | spec.md ✅ | research.md ✅ | data-model.md ✅ | contracts/ ✅

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add new dependencies and wire adapters into lifespan

- [x] T001 Add `cohere`, `pgvector`, `google-genai` to `backend/pyproject.toml` dependencies (switched to Gemini instead of OpenAI)
- [x] T002 [P] Create `backend/app/adapters/embedder.py` — `EmbedderAdapter` with `embed_one()` and `embed_batch()` using Gemini REST API via httpx; API key via `get_secret_value("gemini_api_key")`
- [x] T003 [P] Create `backend/app/adapters/reranker.py` — `RerankerAdapter` with `rerank()` using `cohere` async client; API key via `get_secret_value("cohere_api_key")`; falls back to original order on error and logs warning
- [x] T004 Update `backend/app/lifespan.py` to build `EmbedderAdapter` and `RerankerAdapter` at startup and mount on `app.state.embedder` / `app.state.reranker`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: ORM models, migration, and chunk repository — everything user story phases depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Create `backend/app/db/models/parent_chunk.py` — `ParentChunk` SQLAlchemy ORM model with fields: `id` (UUID PK), `tenant_id` (UUID NOT NULL), `content_id` (UUID), `text` (TEXT), `chunk_index` (INT), `created_at` (TIMESTAMPTZ); RLS policy line in docstring
- [x] T006 Create `backend/app/db/models/child_chunk.py` — `ChildChunk` SQLAlchemy ORM model with fields: `id` (UUID PK), `tenant_id` (UUID NOT NULL), `parent_id` (UUID FK→parent_chunks NOT NULL), `text` (TEXT), `embedding` (Vector(768)), `chunk_index` (INT), `created_at` (TIMESTAMPTZ)
- [x] T007 Create Alembic migration `backend/alembic/versions/0002_chunk_tables.py` — creates `parent_chunks` and `child_chunks` tables with HNSW index on `child_chunks.embedding`; enables `pgvector` extension; adds RLS policies for both tables using `app.current_tenant`
- [x] T008 Create `backend/app/repos/chunk_repo.py` — `ChunkRepo` with: `delete_chunks_for_content`, `write_parent_chunks`, `write_child_chunks`, `search_children`, `fetch_parents_by_ids` — all async, all scoped by `tenant_id`

**Checkpoint**: Foundation ready — user story phases can now begin

---

## Phase 3: User Story 1 — Visitor gets a grounded answer (Priority: P1) 🎯 MVP

**Goal**: A visitor query is embedded, matched against tenant-scoped child chunks, reranked, deduplicated to parents, and returned to the agent.

**Independent Test**: Seed a tenant with known CMS content, ask a question whose answer is in that content, verify top-5 parents contain the answer and no other tenant's chunks appear.

### Implementation

- [x] T009 [US1] Create `backend/app/services/retrieval.py` — implement `retrieve()` per contract
- [x] T010 [US1] Define `RetrievalResult` dataclass and `EmbedError` exception in `backend/app/services/retrieval.py`
- [x] T011 [US1] Wire `retrieve()` into `backend/app/tools/rag_search.py`
- [x] T012 [US1] Create `backend/tests/test_retrieval.py` — 6 unit tests all passing
- [x] T013 [US1] Create `backend/tests/test_chunk_isolation.py` — isolation test passing

**Checkpoint**: User Story 1 complete — retrieval pipeline is live and tenant-isolated ✅

---

## Phase 4: User Story 2 — Tenant admin triggers ingestion (Priority: P2)

**Goal**: Admin calls `POST /ingest`, the service chunks CMS content, embeds children in batches, and writes parent+child rows atomically; idempotent by `content_id`.

**Independent Test**: Publish a new CMS page, trigger ingestion, run a retrieval query that matches the new content, verify it appears in top-5.

### Implementation

- [x] T014 [US2] Create `backend/app/services/ingestion.py` — implement `ingest_tenant_content()` per contract
- [x] T015 [US2] Define `IngestionResult` dataclass and chunker helpers in `backend/app/services/ingestion.py`; enforce 2048-char parent cap and 512-char child cap
- [x] T016 [US2] Add `POST /ingest` route in `backend/app/api/routes/ingest.py`; wired into `backend/app/main.py`
- [x] T017 [US2] Create `backend/tests/test_ingestion.py` — 8 unit tests all passing

**Checkpoint**: User Story 2 complete — ingestion pipeline is live ✅

---

## Phase 5: User Story 3 — Retrieval quality is measurable (Priority: P2)

**Goal**: The team can run `rag_eval.py` against `rag_golden.jsonl` (15 triples) and get hit@5, MRR, faithfulness, and answer relevancy scores; CI blocks on regression.

**Independent Test**: Run eval harness, confirm it outputs all four metrics, confirm removing reranking lowers hit@5.

### Implementation

- [x] T018 [US3] Create `evals/rag_golden.jsonl` — 15 hand-labelled triples (opening hours, returns, shipping, pricing, contact — 3 per topic)
- [x] T019 [US3] Create `evals/rag_eval.py` — CLI with hit@5, MRR, and offline deterministic faithfulness + relevancy proxy metrics; exits non-zero on threshold breach without hosted API keys
- [x] T020 [US3] Update root `eval_thresholds.yaml` — `rag.hit_at_5_min`, `rag.mrr_min`
- [x] T021 [US3] Add eval CI steps to `.github/workflows/ci.yml` — runs the RAG eval harness and gate, blocking merge on non-zero exit

**Checkpoint**: User Story 3 complete — eval harness is live and wired to CI ✅

---

## Phase 6: Polish & Cross-Cutting Concerns

- [ ] T022 [P] Seed Vault with Gemini and Cohere API keys (manual step — see quickstart.md)
- [x] T023 [P] Updated `backend/app/core/config.py` — added `gemini_embedding_model`, `retrieval_top_k`, `reranker_candidate_k`; switched from `groq_*` to `gemini_*`
- [x] T024 Run full test suite — 17/17 passing
- [ ] T025 Run quickstart.md validation end-to-end once Vault keys are seeded (requires live Docker stack)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1)**: Depends on Phase 2 — retrieval needs ORM models + chunk_repo + adapters
- **Phase 4 (US2)**: Depends on Phase 2 — ingestion needs ORM models + chunk_repo + adapters
- **Phase 5 (US3)**: Depends on Phase 3 (needs working retrieval to score)
- **Phase 6 (Polish)**: Depends on Phases 3, 4, 5

### Task Count Summary

| Phase | Tasks | Status |
|-------|-------|--------|
| Phase 1 — Setup | 4 | ✅ Done |
| Phase 2 — Foundational | 4 | ✅ Done |
| Phase 3 — US1 Retrieval | 5 | ✅ Done |
| Phase 4 — US2 Ingestion | 4 | ✅ Done |
| Phase 5 — US3 Eval | 4 | ✅ Done |
| Phase 6 — Polish | 4 | 2/4 (2 need live stack) |
| **Total** | **25** | **23/25** |
