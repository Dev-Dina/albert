# Research: RAG Pipeline

**Feature**: 002-rag-pipeline | **Date**: 2026-05-26

---

## Decision 1: Chunking Strategy

**Decision**: Parent-child chunking (parents ~1024 chars for LLM context, children ~256 chars for similarity search)

**Rationale**: Fixed-size chunking is the naive baseline. Parent-child gives precise embeddings (small child) AND rich context for the LLM (large parent) — the guide ranks this as the single highest-leverage improvement. No architectural change needed beyond storing both sizes.

**Alternatives considered**:
- Fixed-size overlapping chunks: baseline, poor context at boundaries
- Semantic chunking: higher effort, incremental gain once parent-child is in place
- Structure-aware splitting: valuable for markdown/HTML CMS content — can layer on later

---

## Decision 2: Retrieval Improvement

**Decision**: Cross-encoder reranking via Cohere Rerank API

**Rationale**: After initial top-20 vector retrieval, Cohere Rerank re-scores each (query, chunk) pair jointly — far more accurate than bi-encoder similarity alone. Hosted API keeps containers lean (no local model weights, no torch). The before/after hit@5 delta is the number required by the brief.

**Alternatives considered**:
- Local cross-encoder (ms-marco-MiniLM): requires hosting, GPU or tuned CPU, adds container weight
- Query expansion (HyDE/Multi-Query): adds LLM call per query, more latency, better for short/ambiguous queries — not the primary problem here
- MMR deduplication: useful after reranking, can add as polish layer

---

## Decision 3: Embedding Model

**Decision**: `text-embedding-3-small` (OpenAI hosted API)

**Rationale**: Modern model, significantly better than ada-002, low cost, supports batch calls. No re-embedding penalty since this is a new corpus. MTEB top-tier for English text.

**Alternatives considered**:
- `text-embedding-3-large`: higher accuracy, higher cost — overkill for CMS FAQ content
- BGE/E5 (self-hosted): would require a container, violates lean-container rule

---

## Decision 4: k value for retrieval

**Decision**: Retrieve top-20 children for reranking, return top-5 deduplicated parents to LLM

**Rationale**: Top-20 candidate pool gives reranker enough signal to work with; top-5 parents balances context window usage against retrieval coverage. Hit@5 is the primary eval metric — this is consistent with the golden set evaluation.

---

## Decision 5: Ingestion trigger

**Decision**: Admin-triggered only (`POST /ingest` endpoint, called by admin panel button)

**Rationale**: The build plan is explicit — ingestion runs on admin trigger, not on every content change. Auto-ingestion on every save would cause embedding API cost spikes and pgvector churn.

---

## Decision 6: Eval framework

**Decision**: Custom `rag_eval.py` using hit@5 and MRR for retrieval; faithfulness and answer relevancy are scored by a **frozen offline judge rubric** (version-controlled, deterministic key-term coverage) so the CI gate does not require hosted API keys.

**Rationale**: RAGAS or an LLM-as-judge can be used in deeper offline reviews, but the CI gate must be deterministic, free, and runnable on a fresh clone. The committed frozen judge scores key-term support between generated answers, ideal answers, and retrieved chunks. To keep it honest, a hand-labeled subset (`evals/rag_judge_labels.jsonl`, 5 of the 15 golden examples with human pass/fail verdicts) is checked against the judge's pass/fail decisions and the **agreement is reported** (and gated via `rag.judge_agreement_min`). This satisfies the brief's "frozen judge + report agreement with hand labels" option.

**Two-sided calibration**: the hand-labeled subset includes both positive cases and negative calibration cases. Negative records carry an optional `candidate_answer` override (a deliberately unfaithful or irrelevant answer) that the judge re-scores in place of the golden generated answer — so agreement validates that the judge both agrees on good answers and *catches* bad ones, without altering the 15 golden generated answers.

**Honest limitation**: the frozen judge is lexical, not semantic — a CI-safe grading floor, not a replacement for RAGAS / a semantic LLM judge. No hosted LLM judge runs in CI. The lexical rubric makes a "faithful-but-irrelevant" answer hard to construct (retrieved context tracks the question), so the negative set leans on relevant-but-unfaithful and clearly-irrelevant cases.
