"""Tenant-admin CMS content routes (feature 007, US1).

Every endpoint is scoped to the caller's resolved tenant via ``AdminIdentityDep``
— the tenant id derives from the verified ``tenant_admin`` membership, NEVER from
a request body, query string, or path. Create/update/delete schedule a background
re-index so authored content flows into the RAG pipeline without blocking the
admin save.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.admin_widgets import AdminIdentityDep
from app.db.session import get_db
from app.schemas.admin_cms import CmsPageCreate, CmsPageResponse, CmsPageUpdate
from app.services import cms_service as svc

router = APIRouter(prefix="/api/v1/admin/cms", tags=["admin-cms"])


def _to_response(page) -> CmsPageResponse:
    return CmsPageResponse(
        id=page.id,
        title=page.title,
        slug=page.slug,
        body=page.body,
        is_published=page.is_published,
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


@router.get("/pages", response_model=list[CmsPageResponse])
async def list_pages(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    published: bool | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[CmsPageResponse]:
    """List this tenant's content pages (newest first)."""
    pages = await svc.list_pages(
        db, tenant_id=identity.tenant_id, published=published, limit=limit, offset=offset
    )
    return [_to_response(p) for p in pages]


@router.post("/pages", response_model=CmsPageResponse, status_code=status.HTTP_201_CREATED)
async def create_page(
    body: CmsPageCreate,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    background_tasks: BackgroundTasks,
) -> CmsPageResponse:
    try:
        page = await svc.create_page(
            db,
            tenant_id=identity.tenant_id,
            title=body.title,
            body=body.body,
            slug=body.slug,
            is_published=body.is_published,
        )
    except svc.CmsSlugConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"slug already in use: {exc}"
        ) from exc
    await db.commit()
    svc.schedule_reindex(background_tasks, request.app, identity.tenant_id, page.id)
    return _to_response(page)


@router.get("/pages/{page_id}", response_model=CmsPageResponse)
async def get_page(
    page_id: uuid.UUID,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CmsPageResponse:
    try:
        page = await svc.get_page(db, tenant_id=identity.tenant_id, page_id=page_id)
    except svc.CmsPageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="page not found"
        ) from exc
    return _to_response(page)


@router.put("/pages/{page_id}", response_model=CmsPageResponse)
async def update_page(
    page_id: uuid.UUID,
    body: CmsPageUpdate,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    background_tasks: BackgroundTasks,
) -> CmsPageResponse:
    if not body.has_any():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="at least one field must be provided",
        )
    try:
        page = await svc.update_page(
            db,
            tenant_id=identity.tenant_id,
            page_id=page_id,
            title=body.title,
            body=body.body,
            slug=body.slug,
            is_published=body.is_published,
        )
    except svc.CmsPageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="page not found"
        ) from exc
    except svc.CmsSlugConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"slug already in use: {exc}"
        ) from exc
    await db.commit()
    svc.schedule_reindex(background_tasks, request.app, identity.tenant_id, page.id)
    return _to_response(page)


@router.delete("/pages/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(
    page_id: uuid.UUID,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    request: Request,
    background_tasks: BackgroundTasks,
) -> None:
    try:
        await svc.delete_page(db, tenant_id=identity.tenant_id, page_id=page_id)
    except svc.CmsPageNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="page not found"
        ) from exc
    await db.commit()
    svc.schedule_removal(background_tasks, request.app, identity.tenant_id, page_id)
