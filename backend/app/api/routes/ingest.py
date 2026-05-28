import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.db.tenant_session import get_tenant_db
from app.services.ingestion import IngestionResult, ingest_tenant_content

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])


def _get_current_tenant(request: Request) -> str:
    """Resolve the tenant for an ingestion request.

    TODO(Ali): derive tenant from verified admin auth, not client X-Tenant-Id.
    This route is mounted on main; trusting the header is a cross-tenant breach
    vector (local dev only — never trust in production).
    """
    tenant_id = request.headers.get("X-Tenant-Id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant identity required")
    return tenant_id


@router.post("", response_model=None)
async def trigger_ingestion(
    request: Request,
    tenant_id: Annotated[str, Depends(_get_current_tenant)],
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
