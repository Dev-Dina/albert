# Contract: Ingestion Service

**Layer**: Service (`backend/app/services/ingestion.py`)

---

## Interface

```python
async def ingest_tenant_content(
    *,
    tenant_id: str,          # from get_current_tenant() — never from caller
    content_ids: list[str] | None = None,  # None = re-ingest all tenant content
    db: AsyncSession,
    embedder: EmbedderAdapter,
) -> IngestionResult
```

## IngestionResult

```python
@dataclass
class IngestionResult:
    tenant_id: str
    pages_processed: int
    parent_chunks_written: int
    child_chunks_written: int
    errors: list[str]          # per-page errors, if any
    success: bool
```

## Behaviour contract

- Pulls CMS content rows via `content_repo` (Owner A's repo), scoped to `tenant_id`
- Splits each page into parent chunks (~1024 chars) then child chunks (~256 chars)
- Embeds children in batches of 100 via `EmbedderAdapter.embed_batch()`
- Tags every embed call with `tenant_id` via cost tracker
- Writes parent then child rows in a single transaction per page — no partial writes
- Idempotent: deletes existing chunks for a `content_id` before writing new ones
- On embed API error: skips the page, records error in `IngestionResult.errors`, continues
- `tenant_id` is NEVER read from the content rows — always the injected parameter

## Failure modes

| Condition | Behaviour |
|---|---|
| Embed API unreachable | Skip page, record error, continue with remaining pages |
| DB write failure | Rollback transaction for that page, record error |
| Empty content body | Skip page silently |
| All pages fail | Returns `success=False` with all errors listed |
