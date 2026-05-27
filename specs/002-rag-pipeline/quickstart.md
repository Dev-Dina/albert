# Quickstart: RAG Pipeline

## Run ingestion (local dev)

```bash
# Trigger ingestion for a tenant via the API (once the route exists)
curl -X POST http://localhost:8000/ingest \
  -H "Authorization: Bearer <tenant_admin_jwt>" \
  -H "Content-Type: application/json"
```

## Run retrieval test manually

```python
# From a Python shell inside the backend container
import asyncio
from app.services.retrieval import retrieve
from app.db.session import AsyncSessionLocal

async def test():
    async with AsyncSessionLocal() as db:
        results = await retrieve(
            tenant_id="your-tenant-uuid",
            query="What are your opening hours?",
            db=db,
            # embedder and reranker injected from app.state in real requests
        )
        for r in results:
            print(r.text[:100])

asyncio.run(test())
```

## Run the eval harness

```bash
cd backend
uv run python -m evals.rag_eval --golden evals/rag_golden.jsonl
```

## Run tests

```bash
cd backend
uv run pytest tests/test_ingestion.py tests/test_retrieval.py tests/test_chunk_isolation.py -v
```

## Environment variables needed

```
OPENAI_API_KEY=<from Vault: secret/app/openai_api_key>
COHERE_API_KEY=<from Vault: secret/app/cohere_api_key>
```

Seed Vault:
```bash
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=dev-root-token \
  albert-vault-1 vault kv put secret/app/openai_api_key openai_api_key=sk-...
docker exec -e VAULT_ADDR=http://127.0.0.1:8200 -e VAULT_TOKEN=dev-root-token \
  albert-vault-1 vault kv put secret/app/cohere_api_key cohere_api_key=...
```
