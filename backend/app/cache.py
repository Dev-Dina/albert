"""Caching policy for Albert.

Owner A decision (coordinate with Owner B who owns retrieval).

## What we cache

Nothing by default in Phase 1.

The deliberate choice is NOT to cache tenant-owned content or RAG results at the
application layer.  The reasons, in priority order:

1. **Tenant isolation risk** — a cached response keyed on a query string could be
   served to a different tenant if the cache key does not include tenant_id.
   Getting cache-key design wrong is a one-line cross-tenant breach.  We cannot
   afford that risk until the cache invalidation story is fully designed.

2. **Correctness over latency** — a tenant admin updating a CMS page must see the
   change reflected immediately.  An application-layer cache without an invalidation
   hook would serve stale content silently.

3. **Pgvector already uses an HNSW index** — retrieval latency at typical tenant
   scale (< 100k chunks) is < 20ms.  Caching retrieval results adds complexity
   before there is evidence of a bottleneck.

## What we explicitly do NOT cache

- RAG retrieval results (tenant-specific, staleness risk)
- Conversation history (append-only, must be fresh)
- CMS pages (editable by tenant admin, must invalidate on write)
- Widget config / allowed origins (security-critical, must not be stale)
- JWT tokens (stateless, cached by the client's HTTP layer)

## Future: where caching makes sense

These are the correct targets once the invalidation story is designed:

- **Embedding cache** — keyed on (model, text_hash).  Embeddings are deterministic
  and model-version-stable.  Safe because the key does not contain tenant_id and the
  value is a vector, not tenant content.  Owner C (model server) should own this.

- **Per-tenant rate-limit counter** — already in Redis (ratelimit.py).  This IS a
  form of caching/counting and is already implemented with a tenant-scoped key.

- **Tenant config hot path** — after profiling shows the tenant row is fetched on
  every request, a short TTL (5–30s) cache keyed on tenant_id is safe because
  config changes are rare and a brief staleness window is acceptable.

## Coordination note

Owner B owns the retrieval pipeline and pgvector queries.  Any embedding or retrieval
cache MUST:
  - Include tenant_id in the cache key if the cached value is tenant-specific.
  - Invalidate on CMS page write/delete.
  - Be reviewed by Owner A before merging (isolation risk).

The Redis instance in docker-compose is shared infrastructure.  Cache keys must use
a distinct prefix (e.g. ``cache:``) to avoid colliding with rate-limit keys (``rl:``).
"""
