# Feature Specification: RAG Pipeline

**Feature Branch**: `002-rag-pipeline`

**Created**: 2026-05-26

**Status**: Draft

**Input**: User description: "RAG pipeline: parent-child chunking, tenant-filtered pgvector retrieval with cross-encoder reranking, batch embedding ingestion, and eval harness (hit@5, MRR, faithfulness)"

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Visitor gets a grounded answer from tenant content (Priority: P1)

A visitor asks a question on the embedded widget. The agent retrieves relevant chunks from that tenant's CMS content and formulates an answer grounded in those chunks — not hallucinated.

**Why this priority**: Without retrieval the agent can only guess. Retrieval is the core value of RAG.

**Independent Test**: Seed a tenant with known CMS content, ask a question whose answer appears in that content, verify the retrieved chunks contain the answer and the agent's reply is faithful to them.

**Acceptance Scenarios**:

1. **Given** a tenant has CMS content about "return policy", **When** a visitor asks "What is your return policy?", **Then** the retrieval system returns at least one chunk containing return policy information ranked in the top 5 results.
2. **Given** two tenants exist with different CMS content, **When** Tenant A's visitor asks a question, **Then** only Tenant A's chunks are returned — no Tenant B chunks appear in any result.
3. **Given** no relevant content exists for a query, **When** retrieval runs, **Then** an empty result set is returned without error, and the agent responds honestly that it does not have that information.

---

### User Story 2 — Tenant admin triggers content ingestion (Priority: P2)

A tenant admin clicks "Ingest" in the admin panel after publishing new CMS content. The system chunks, embeds, and indexes the content so it is searchable immediately.

**Why this priority**: Without ingestion, retrieval has nothing to search. Admin-triggered ingestion is the write side of the pipeline.

**Independent Test**: Publish a new CMS page, trigger ingestion, then run a retrieval query that should match the new content and verify it appears in results.

**Acceptance Scenarios**:

1. **Given** a tenant admin triggers ingestion, **When** ingestion completes, **Then** the new content chunks are searchable within the same session.
2. **Given** a large content set (100+ pages), **When** ingestion runs, **Then** it completes without timeout and all pages are indexed.
3. **Given** ingestion fails mid-way (e.g. embedding API error), **When** the error occurs, **Then** no partial or corrupted chunks are written — the pipeline fails cleanly and is safe to retry.

---

### User Story 3 — Retrieval quality is measurable and improvable (Priority: P2)

The team can run an evaluation harness against a golden set of questions to measure retrieval quality (hit@5, MRR) and generation quality (faithfulness, answer relevancy), and compare before/after a pipeline change.

**Why this priority**: "Better retrieval" without a number is a guess. The eval harness is what turns engineering decisions into defensible choices.

**Independent Test**: Run the eval harness against the golden set, confirm it outputs hit@5, MRR, faithfulness, and answer relevancy scores, and that lowering retrieval quality (e.g. removing reranking) measurably reduces the scores.

**Acceptance Scenarios**:

1. **Given** a golden set of 15 question/answer/chunk triples, **When** the eval harness runs, **Then** it outputs hit@5 ≥ 0.6 and MRR ≥ 0.5 with reranking enabled.
2. **Given** reranking is disabled, **When** the eval harness runs on the same golden set, **Then** hit@5 and MRR scores are measurably lower than with reranking — proving the improvement is real.
3. **Given** the eval harness runs in CI, **When** a change regresses hit@5 below the committed threshold, **Then** CI blocks the merge.

---

### Edge Cases

- What happens when a tenant has no CMS content yet? Retrieval must return empty results without error.
- What happens when the embedding API is unavailable during ingestion? The pipeline must fail fast, log the error, and leave no partial state.
- What happens when a chunk's parent is missing? The retrieval deduplication step must skip orphaned children gracefully.
- What happens when two ingestion jobs run concurrently for the same tenant? The system must not produce duplicate chunks.
- What happens when a query embedding call fails? Retrieval must surface the error to the caller rather than returning empty results silently.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST split tenant CMS content into parent chunks (large, for LLM context) and child chunks (small, for precise similarity search), with each child linked to its parent.
- **FR-002**: The system MUST embed only child chunks during ingestion, using a hosted embedding API called in batches.
- **FR-003**: Every chunk (parent and child) MUST carry a `tenant_id` field. Retrieval MUST filter by `tenant_id` at both the session/RLS layer and the repository layer.
- **FR-004**: The system MUST accept ingestion requests on an admin-triggered basis only — not automatically on every content change or visitor request.
- **FR-005**: At query time, the system MUST embed the visitor's query, retrieve the top candidate child chunks by similarity, apply cross-encoder reranking to re-score them, deduplicate to their parent chunks, and return the top-k parent chunks to the agent.
- **FR-006**: Every embedding call during ingestion MUST be tagged with `tenant_id` for cost attribution.
- **FR-007**: The system MUST provide an evaluation harness that measures hit@5, MRR, faithfulness, and answer relevancy against a hand-labelled golden set of 15 triples.
- **FR-008**: The eval harness MUST be runnable in CI and MUST fail if hit@5 falls below the committed threshold in `eval_thresholds.yaml`.
- **FR-009**: Retrieval MUST return the top-5 parent chunks by default (k=5), with the value justified in `specs/rag_pipeline.md`.
- **FR-010**: Ingestion MUST fail cleanly on error — no partial chunk writes, safe to retry.

### Key Entities

- **Parent chunk**: Large text segment (e.g. 1024–2048 chars) stored for LLM context. Has `tenant_id`, `content_id`, `text`, `id`.
- **Child chunk**: Small text segment (e.g. 256 chars) used only for similarity search. Has `tenant_id`, `parent_id`, `text`, `embedding`, `id`.
- **Ingestion job**: Admin-triggered process that reads CMS content, chunks it, embeds children, and writes to the vector store.
- **Retrieval result**: Ordered list of parent chunk texts returned to the agent after reranking and deduplication.
- **Golden triple**: A hand-labelled evaluation record: `{question, ideal_answer, ground_truth_chunk_ids}`.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Retrieval returns the correct parent chunk in the top 5 results for at least 60% of golden set questions (hit@5 ≥ 0.6) with reranking enabled.
- **SC-002**: Reranking demonstrably improves hit@5 over naive top-k retrieval — the before/after delta is recorded in `docs/DECISIONS.md`.
- **SC-003**: A visitor on Tenant A can never receive a chunk belonging to Tenant B — verified by a two-tenant test that passes in CI.
- **SC-004**: Ingestion of 50 CMS pages completes without timeout or partial writes.
- **SC-005**: The eval harness runs end-to-end in CI in under 60 seconds on the 15-triple golden set.
- **SC-006**: Every embedding call during ingestion is attributable to a specific tenant in the cost tracker.

---

## Assumptions

- Owner A will deliver the `CMSContent` model and repo before the ingestion service can be fully wired; the ingestion service is written to stub that dependency until then.
- Owner A will deliver the cost-attribution wrapper; embedding calls reference it but fall back to a no-op stub until delivery.
- The hosted embedding API (e.g. OpenAI `text-embedding-3-small` or equivalent) supports batch calls of at least 100 texts per request.
- Cross-encoder reranking uses the Cohere Rerank API (hosted, no local model weights) to keep containers lean.
- k=5 parent chunks is the default return value — chosen to balance context window usage against retrieval coverage; this number is justified with a hit@5 measurement.
- The golden set of 15 triples is hand-labelled against seeded demo tenant content before Tuesday EOD.
- Faithfulness and answer relevancy are measured using an LLM-as-judge approach (e.g. RAGAS or equivalent) — no human labelling required for generation metrics.
- Ingestion is idempotent by content ID — re-ingesting the same content replaces existing chunks rather than duplicating them.
