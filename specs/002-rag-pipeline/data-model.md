# Data Model: RAG Pipeline

**Feature**: 002-rag-pipeline | **Date**: 2026-05-26

---

## Entities

### ParentChunk

Stores large text segments for LLM context. Never embedded — used only as the return value to the agent.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Server-generated |
| `tenant_id` | UUID (FK → tenants, NOT NULL) | RLS policy enforced |
| `content_id` | UUID (FK → cms_content) | Source CMS page |
| `text` | TEXT NOT NULL | 1024–2048 chars |
| `chunk_index` | INT NOT NULL | Position in document |
| `created_at` | TIMESTAMPTZ | Server default NOW() |

**Indexes**: `(tenant_id)`, `(content_id)`
**RLS**: `USING (tenant_id = current_setting('app.current_tenant')::uuid)`

---

### ChildChunk

Stores small text segments used only for similarity search. Linked to parent for context retrieval.

| Field | Type | Notes |
|---|---|---|
| `id` | UUID (PK) | Server-generated |
| `tenant_id` | UUID (FK → tenants, NOT NULL) | RLS policy enforced |
| `parent_id` | UUID (FK → parent_chunks, NOT NULL) | Link to parent |
| `text` | TEXT NOT NULL | ~256 chars |
| `embedding` | vector(1536) | `text-embedding-3-small` dimensions |
| `chunk_index` | INT NOT NULL | Position within parent |
| `created_at` | TIMESTAMPTZ | Server default NOW() |

**Indexes**: `(tenant_id)`, `(parent_id)`, HNSW index on `embedding` with `tenant_id` as filter
**RLS**: `USING (tenant_id = current_setting('app.current_tenant')::uuid)`

---

## Relationships

```
cms_content (Owner A)
    │
    └── parent_chunks (1:N, scoped by tenant_id)
            │
            └── child_chunks (1:N, scoped by tenant_id)
                    │
                    └── embedding (vector(1536), HNSW indexed)
```

---

## State Transitions

**Ingestion flow**:
```
CMS content page
  → split into parent chunks
    → split each parent into child chunks
      → batch embed children (hosted API)
        → write parent_chunks rows
          → write child_chunks rows with embeddings
```

**Retrieval flow**:
```
query string
  → embed query (hosted API)
    → ANN search over child_chunks (tenant-filtered, top-20)
      → rerank (query, child) pairs (Cohere API)
        → deduplicate to parent_ids (top-5 unique)
          → fetch parent_chunk texts
            → return to agent
```

---

## Validation Rules

- `tenant_id` is NEVER supplied by the caller — always injected from `get_current_tenant()`
- `embedding` dimension MUST match the model's output dimension (1536 for `text-embedding-3-small`)
- Ingestion is idempotent by `content_id` — re-ingest replaces existing chunks for that content page
- Child chunk text MUST NOT exceed 512 chars (soft cap, enforced in chunker)
- Parent chunk text MUST NOT exceed 2048 chars (soft cap, enforced in chunker)
