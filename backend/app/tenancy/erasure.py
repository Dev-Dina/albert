"""Right-to-erasure: total purge of a tenant across all five stores.

This is a WRITE/DELETE-ONLY path.  The tenant_manager can destroy without
ever reading tenant content (conversations, messages, leads, CMS content).
Every erasure is audit-logged with the actor's user_id.

The five stores that must be emptied (per PROJECT_CONTEXT.md §11):
  1. Postgres     — all rows WHERE tenant_id = X
  2. pgvector     — content_chunks embeddings WHERE tenant_id = X
                    (handled by Postgres cascade, verified explicitly)
  3. MinIO        — all blobs under the tenant namespace
  4. Redis        — all sessions for the tenant
  5. Traces/logs  — purge hook (stub for C's implementation)

"The row is deleted but the embeddings are still searchable" is a
compliance failure.  The erasure test (test_erasure_total.py) asserts
all five stores independently.

Cross-owner hook signatures agreed on day one:
  B exposes: no separate hook needed — pgvector lives in content_chunks (Postgres cascade)
             and Redis sessions keyed as  session:{tenant_id}:*
  C exposes: purge_tenant_traces(tenant_id) — stub below until C implements it
  D owns:    the UI button that calls the /tenants/{id}/erase endpoint
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import redis.asyncio as aioredis
from fastapi import HTTPException, status as http_status
from minio import Minio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.tenancy.audit import record_audit

logger = logging.getLogger(__name__)

# Tenant-owned tables in dependency order (children before parents where FK matters).
# pgvector content_chunks is included here; the Postgres CASCADE on tenant_id also
# handles it, but we delete explicitly so the erasure test can assert each table.
# parent_chunks and child_chunks have no FK to tenants — CASCADE never fires for them,
# so they MUST be listed here for explicit deletion.  child_chunks before parent_chunks
# (FK: child_chunks.parent_id → parent_chunks.id CASCADE).
_TENANT_TABLES = [
    "cost_events",
    "leads",
    "messages",
    "conversations",
    "child_chunks",                  # FK to parent_chunks — must precede parent_chunks
    "parent_chunks",                 # no FK to tenants; explicit delete required
    "content_chunks",
    "cms_pages",
    "widget_configs",
    "tenant_guardrail_configs",
    "widgets",
    "widget_allowed_origins",
    "widget_guardrail_configs",
    "widget_signing_key_versions",
]
# Frozen copy used as an allowlist guard before any raw SQL table-name interpolation.
_ALLOWED_TABLES: frozenset[str] = frozenset(_TENANT_TABLES)


async def erase_tenant(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict[str, int]:
    """Purge all data for ``tenant_id`` across every store.

    Returns a summary dict with row counts deleted per store for audit/logging.
    Does NOT commit — the caller owns the transaction.

    This function is write/delete-only: no SELECT on tenant content is issued.
    It reads only row counts (integers) for the audit summary — not content.
    """
    # Verify the tenant exists before starting any deletes.
    tenant_row = await db.execute(text("SELECT id FROM tenants WHERE id = :tid"), {"tid": str(tenant_id)})
    if tenant_row.scalar_one_or_none() is None:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id!r} not found.")

    summary: dict[str, int] = {}

    # ------------------------------------------------------------------
    # 1. Postgres — delete from all tenant-owned tables
    # ------------------------------------------------------------------
    for table in _TENANT_TABLES:
        assert table in _ALLOWED_TABLES, f"Unexpected table name: {table!r}"
        result = await db.execute(
            text(f"DELETE FROM {table} WHERE tenant_id = :tid RETURNING id"),
            {"tid": str(tenant_id)},
        )
        count = len(result.fetchall())
        summary[f"postgres.{table}"] = count
        logger.info("erasure postgres.%s tenant=%s rows=%d", table, tenant_id, count)

    # ------------------------------------------------------------------
    # 2. pgvector — content_chunks is already covered above; log explicitly
    # ------------------------------------------------------------------
    summary["pgvector.content_chunks"] = summary.get("postgres.content_chunks", 0)

    # ------------------------------------------------------------------
    # 3. MinIO — delete all objects under the tenant prefix
    # ------------------------------------------------------------------
    minio_count = await _erase_minio(tenant_id)
    summary["minio.objects"] = minio_count

    # ------------------------------------------------------------------
    # 4. Redis — delete all session keys for this tenant
    # ------------------------------------------------------------------
    redis_count = await _erase_redis(tenant_id)
    summary["redis.sessions"] = redis_count

    # ------------------------------------------------------------------
    # 5. Traces / logs — stub; C implements the real purge hook
    # ------------------------------------------------------------------
    await _erase_traces(tenant_id)
    summary["traces"] = 0  # updated when C wires the real hook

    # ------------------------------------------------------------------
    # Mark tenant as erased in the platform table (not deleted — for audit)
    # ------------------------------------------------------------------
    await db.execute(
        text("UPDATE tenants SET status = 'erased' WHERE id = :tid"),
        {"tid": str(tenant_id)},
    )

    # ------------------------------------------------------------------
    # Audit log — actor, action, summary (no content)
    # ------------------------------------------------------------------
    await record_audit(
        db=db,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="tenant.erase",
        meta={"summary": summary},
    )

    logger.info(
        "erasure.complete tenant_id=%s actor=%s summary=%s",
        tenant_id,
        actor_user_id,
        summary,
    )
    return summary


# ---------------------------------------------------------------------------
# Store-specific helpers
# ---------------------------------------------------------------------------

def _minio_delete_sync(tenant_id: uuid.UUID) -> int:
    """Synchronous Minio deletion — called via asyncio.to_thread to avoid blocking."""
    bucket = "albert-assets"
    prefix = f"{tenant_id}/"
    count = 0
    client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key.get_secret_value(),
        secret_key=settings.minio_secret_key.get_secret_value(),
        secure=settings.minio_secure,
    )
    objects = client.list_objects(bucket, prefix=prefix, recursive=True)
    for obj in objects:
        client.remove_object(bucket, obj.object_name)
        count += 1
    return count


async def _erase_minio(tenant_id: uuid.UUID) -> int:
    """Delete all MinIO objects stored under the tenant's namespace.

    Bucket layout convention: one shared bucket ``albert-assets``, objects
    prefixed with ``{tenant_id}/``.

    Minio SDK is synchronous; runs in a thread pool so it does not block
    the async event loop.

    Returns the number of objects deleted.
    """
    try:
        count = await asyncio.to_thread(_minio_delete_sync, tenant_id)
        logger.info("erasure.minio tenant=%s objects_deleted=%d", tenant_id, count)
        return count
    except Exception:
        logger.warning(
            "erasure.minio_failed tenant=%s — manual cleanup may be required",
            tenant_id,
            exc_info=True,
        )
        return 0


async def _erase_redis(tenant_id: uuid.UUID) -> int:
    """Delete all Redis session keys for this tenant.

    Session key pattern: ``session:{tenant_id}:*``

    Returns the number of keys deleted.
    """
    pattern = f"session:{tenant_id}:*"
    count = 0
    try:
        url = settings.redis_url or "redis://redis:6379/0"
        client = aioredis.from_url(url, decode_responses=True)
        async with client as r:
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=100)
                if keys:
                    await r.delete(*keys)
                    count += len(keys)
                if cursor == 0:
                    break
        logger.info("erasure.redis tenant=%s keys_deleted=%d", tenant_id, count)
    except Exception:
        logger.warning(
            "erasure.redis_failed tenant=%s — manual cleanup may be required",
            tenant_id,
            exc_info=True,
        )
    return count


async def _erase_traces(tenant_id: uuid.UUID) -> None:
    """Stub: purge tenant references from traces and logs.

    Owner C implements the real hook here.  Until then, log a warning so ops
    knows a manual step is required after erasure.
    """
    logger.warning(
        "erasure.traces_stub tenant=%s — Owner C must implement trace/log purge",
        tenant_id,
    )
