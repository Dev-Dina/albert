# Implementation Plan: RAG Pipeline

**Branch**: `002-rag-pipeline` | **Date**: 2026-05-26 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/002-rag-pipeline/spec.md`

---

## Summary

Build a tenant-isolated RAG pipeline over CMS content: parent-child chunking for precise retrieval with rich LLM context, batch embedding ingestion into tenant-filtered pgvector, cross-encoder reranking as the one justified improvement, and an eval harness (hit@5, MRR, faithfulness, answer relevancy) wired into CI.

---

## Technical Context

**Language/Version**: Python 3.12

**Primary Dependencies**: `openai` (embeddings), `cohere` (reranking), `sqlalchemy[asyncio]`, `pgvector`, `asyncpg`, `httpx`, `pydantic`

**Storage**: PostgreSQL + pgvector — `parent_chunks` and `child_chunks` tables, both with `tenant_id` column covered by RLS

**Testing**: `pytest` + `pytest-asyncio`, mock embedding client for unit tests, real pgvector for integration tests

**Target Platform**: Linux container (backend service)

**Project Type**: Backend service layer (services + repositories)

**Performance Goals**: Retrieval p95 < 500ms including reranking; ingestion throughput ≥ 50 pages/minute

**Constraints**: No `torch` or `transformers` in any container; embedding via hosted API only; reranking via hosted API (Cohere) only; all chunks must carry `tenant_id`

**Scale/Scope**: Per-tenant corpus; initial target 100–1000 CMS pages per tenant

---

## Constitution Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Tenant Isolation — every chunk has `tenant_id`, filtered at RLS + repo layer | ✅ PASS | Both `parent_chunks` and `child_chunks` carry `tenant_id`; retrieval filters at session AND repo layer |
| I. Tenant identity from verified token, not request body | ✅ PASS | `tenant_id` injected from `get_current_tenant` dependency, never from caller |
| II. Layered architecture — services / repositories / schemas separated | ✅ PASS | `ingestion.py` (service), `retrieval.py` (service), `chunk_repo.py` (repository) |
| II. Async patterns throughout | ✅ PASS | All DB and API calls are async |
| III. No secrets hardcoded — embedding + reranking API keys from Vault | ✅ PASS | Keys fetched via `get_secret_value()` at lifespan |
| IV. Tests for all changed behavior | ✅ PASS | Unit tests for chunking, integration tests for retrieval isolation, eval harness for quality |
| V. Spec-driven delivery — spec written before code | ✅ PASS | This plan follows `spec.md` |

**No violations. Cleared to proceed.**

---

## Project Structure

### Documentation (this feature)

```text
specs/002-rag-pipeline/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output
├── quickstart.md        ← Phase 1 output
├── contracts/
│   ├── ingestion.md
│   └── retrieval.md
└── tasks.md             ← /speckit-tasks output (not created here)
```

### Source Code

```text
backend/
├── app/
│   ├── services/
│   │   ├── ingestion.py       ← chunk + embed + write pipeline
│   │   └── retrieval.py       ← embed query + search + rerank + dedupe
│   ├── repos/
│   │   └── chunk_repo.py      ← tenant-scoped DB access for chunks
│   ├── adapters/
│   │   ├── llm.py             ← already exists (Monday)
│   │   ├── embedder.py        ← NEW: hosted embedding API wrapper
│   │   └── reranker.py        ← NEW: Cohere rerank API wrapper
│   └── db/
│       └── models/
│           ├── parent_chunk.py  ← NEW: ORM model
│           └── child_chunk.py   ← NEW: ORM model
├── alembic/versions/
│   └── 0002_chunk_tables.py   ← NEW: migration for both chunk tables
└── tests/
    ├── test_ingestion.py
    ├── test_retrieval.py
    └── test_chunk_isolation.py

evals/
├── rag_golden.jsonl           ← 15 hand-labelled triples
└── rag_eval.py                ← hit@5, MRR, faithfulness, answer relevancy
```

---

## Complexity Tracking

No constitution violations — no justification required.
