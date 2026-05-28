import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.deps import get_admin_tenant_id
from app.db.tenant_session import get_tenant_db
from app.services.ingestion import IngestionResult, ingest_tenant_content

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])


@router.post("", response_model=None)
async def trigger_ingestion(
    request: Request,
    tenant_id: Annotated[str, Depends(get_admin_tenant_id)],
) -> IngestionResult:
    """Admin-triggered ingestion for a tenant's CMS content.

    tenant_id comes from verified auth (stub: X-Tenant-Id header for local dev).
    RLS session variable app.current_tenant is set via get_tenant_db.
    """
    logger.info("ingest.trigger tenant=%s", tenant_id)
    embedder = request.app.state.embedder

    async for db in get_tenant_db(tenant_id):
        return await ingest_tenant_content(
            tenant_id=tenant_id,
            db=db,
            embedder=embedder,
        )
