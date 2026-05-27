# Contract: Retrieval Service

**Layer**: Service (`backend/app/services/retrieval.py`)

---

## Interface

```python
async def retrieve(
    *,
    tenant_id: str,          # from get_current_tenant() — never from caller
    query: str,
    top_k: int = 5,          # number of parent chunks to return
    candidate_k: int = 20,   # children fetched before reranking
    db: AsyncSession,
    embedder: EmbedderAdapter,
    reranker: RerankerAdapter,
) -> list[RetrievalResult]
```

## RetrievalResult

```python
@dataclass
class RetrievalResult:
    parent_chunk_id: str
    text: str              # parent chunk text — returned to LLM
    score: float           # reranker score
    source_content_id: str
```

## Behaviour contract

- Embeds `query` via `EmbedderAdapter.embed_one()`
- Searches `child_chunks` filtered by `tenant_id` (RLS + repo layer), returns top `candidate_k`
- Calls `RerankerAdapter.rerank(query, child_texts)` → re-scored list
- Deduplicates children to unique `parent_id`s, takes top `top_k`
- Fetches parent chunk texts by `parent_id`s (scoped to `tenant_id`)
- Returns ordered list of `RetrievalResult`
- Returns empty list (not an error) if no chunks exist for the tenant
- NEVER returns chunks from a different tenant — enforced at RLS + repo layer

## Failure modes

| Condition | Behaviour |
|---|---|
| Embed API error | Raises `EmbedError` — caller handles, does not return empty silently |
| Reranker API error | Falls back to original similarity order, logs warning |
| No chunks found for tenant | Returns `[]` |
| `query` is empty string | Raises `ValueError` before any API call |
