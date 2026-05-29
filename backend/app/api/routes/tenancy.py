"""Tenancy management routes — tenant_manager only.

All endpoints here require the tenant_manager role.  No endpoint in this
router returns tenant conversation, message, lead, or CMS content — only
lifecycle state and numeric aggregates.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles import TenantManagerDep
from app.cost import (
    aggregate_cost_all_tenants,
    aggregate_cost_for_tenant,
    aggregate_cost_series_all_tenants,
)
from app.db.models.tenant import Tenant
from app.db.session import get_db
from app.schemas.tenancy_audit import AuditEntryResponse
from app.schemas.tenancy_cost import CostSeriesResponse
from app.tenancy.audit import get_audit_log, list_all_cross_tenant
from app.tenancy.erasure import erase_tenant
from app.tenancy.provisioning import (
    AdminNotFoundError,
    LastAdminError,
    TenantNotFoundError,
    add_tenant_admin,
    create_platform_manager,
    provision_tenant,
    reactivate_tenant,
    remove_tenant_admin,
    suspend_tenant,
)

router = APIRouter(prefix="/tenants", tags=["tenancy"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProvisionRequest(BaseModel):
    name: str
    first_admin_email: EmailStr
    first_admin_password: str


class ProvisionResponse(BaseModel):
    tenant_id: uuid.UUID
    name: str
    slug: str
    status: str
    first_admin_user_id: uuid.UUID


class TenantStatusResponse(BaseModel):
    tenant_id: uuid.UUID
    status: str


class EraseResponse(BaseModel):
    tenant_id: uuid.UUID
    summary: dict[str, Any]


class TenantDetailResponse(BaseModel):
    tenant_id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    updated_at: datetime


class AddAdminRequest(BaseModel):
    email: EmailStr
    password: str


class AddAdminResponse(BaseModel):
    admin_user_id: uuid.UUID
    email: str
    tenant_id: uuid.UUID


class RemoveAdminResponse(BaseModel):
    tenant_id: uuid.UUID
    removed_user_id: uuid.UUID


class CreateManagerRequest(BaseModel):
    email: EmailStr
    password: str


class CreateManagerResponse(BaseModel):
    manager_user_id: uuid.UUID
    email: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("", response_model=list[TenantDetailResponse])
async def list_tenants(
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[TenantDetailResponse]:
    """List all tenants (manager dashboard).

    Returns lifecycle metadata only — no conversation, message, lead, or CMS content.
    """
    result = await db.execute(
        select(Tenant).order_by(Tenant.created_at.desc()).limit(limit).offset(offset)
    )
    tenants = result.scalars().all()
    return [
        TenantDetailResponse(
            tenant_id=t.id,
            name=t.name,
            slug=t.slug,
            status=t.status,
            created_at=t.created_at,
            updated_at=t.updated_at,
        )
        for t in tenants
    ]


# NOTE: the literal ``/audit`` and ``/cost/series`` routes are declared BEFORE
# the parametrized ``/{tenant_id}`` route so a request to ``/tenants/audit`` is
# not captured by ``/{tenant_id}`` (which would 422 on an invalid UUID).


@router.get("/audit", response_model=list[AuditEntryResponse])
async def list_cross_tenant_audit(
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    before_id: uuid.UUID | None = Query(default=None),
) -> list[AuditEntryResponse]:
    """Cross-tenant audit timeline (manager-only; FR-050 exception 3).

    Returns the newest audit rows across ALL tenants in one call, for the
    single Audit Log timeline (FR-016). NEVER returns tenant conversation,
    message, lead, or CMS content — only the fields on ``AuditEntryResponse``
    (asserted by the content-exclusion test).
    """
    rows = await list_all_cross_tenant(db=db, limit=limit, before_id=before_id)
    return [
        AuditEntryResponse(
            entry_id=entry.id,
            actor_user_id=entry.actor_user_id,
            actor_email=actor_email,
            action=entry.action,
            target_tenant_id=entry.target_tenant_id,
            target_tenant_slug=target_slug,
            created_at=entry.created_at,
            meta=entry.meta,
        )
        for (entry, actor_email, target_slug) in rows
    ]


@router.get("/cost/series", response_model=list[CostSeriesResponse])
async def get_all_tenants_cost_series(
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    since: datetime | None = None,
    until: datetime | None = None,
    granularity: str = Query(default="daily"),
) -> list[CostSeriesResponse]:
    """Per-tenant daily cost series in ONE batched call (FR-050 exception 4).

    Backs the Cost Overview sparkline (FR-015) without a per-row fan-out.
    Numeric daily buckets only — no tenant content. Manager-only.
    """
    series = await aggregate_cost_series_all_tenants(
        db=db, since=since, until=until, granularity=granularity
    )
    return [CostSeriesResponse(**item) for item in series]


@router.get("/{tenant_id}", response_model=TenantDetailResponse)
async def get_tenant(
    tenant_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantDetailResponse:
    """Get a single tenant's lifecycle metadata.

    Returns status, slug, and timestamps — no tenant content.
    """
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tenant {tenant_id!r} not found.")
    return TenantDetailResponse(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


@router.post("", response_model=ProvisionResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: ProvisionRequest,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProvisionResponse:
    """Provision a new tenant and invite its first admin.

    Only tenant_manager may call this.  The platform operator never logs
    into the new tenant — the first admin configures it from there.
    """
    try:
        tenant, admin = await provision_tenant(
            db=db,
            actor_user_id=current.user_id,
            name=body.name,
            first_admin_email=body.first_admin_email,
            first_admin_password=body.first_admin_password,
        )
    except ValueError as exc:
        msg = str(exc)
        code = status.HTTP_409_CONFLICT if "already exists" in msg else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=msg)
    await db.commit()
    return ProvisionResponse(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        first_admin_user_id=admin.id,
    )


@router.post("/{tenant_id}/suspend", response_model=TenantStatusResponse)
async def suspend(
    tenant_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantStatusResponse:
    """Suspend a tenant (does not delete data)."""
    try:
        tenant = await suspend_tenant(db=db, actor_user_id=current.user_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    await db.commit()
    return TenantStatusResponse(tenant_id=tenant.id, status=tenant.status)


@router.post("/{tenant_id}/reactivate", response_model=TenantStatusResponse)
async def reactivate(
    tenant_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TenantStatusResponse:
    """Lift a suspension and restore a tenant to active status."""
    try:
        tenant = await reactivate_tenant(db=db, actor_user_id=current.user_id, tenant_id=tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    await db.commit()
    return TenantStatusResponse(tenant_id=tenant.id, status=tenant.status)


@router.delete("/{tenant_id}", response_model=EraseResponse)
async def erase(
    tenant_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EraseResponse:
    """Permanently erase a tenant across all five stores.

    Write/delete-only path: the manager can destroy without ever reading
    tenant content.  Returns a summary of rows deleted per store.
    """
    summary = await erase_tenant(db=db, actor_user_id=current.user_id, tenant_id=tenant_id)
    await db.commit()
    return EraseResponse(tenant_id=tenant_id, summary=summary)


# ---------------------------------------------------------------------------
# Admin management (manager-only)
# ---------------------------------------------------------------------------

@router.post("/{tenant_id}/admins", response_model=AddAdminResponse, status_code=status.HTTP_201_CREATED)
async def add_admin(
    tenant_id: uuid.UUID,
    body: AddAdminRequest,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AddAdminResponse:
    """Add a new tenant_admin to an existing active tenant.

    Creates a new user account and assigns it the tenant_admin role for this
    tenant.  The tenant must be active; suspended and erased tenants are
    rejected.  The supplied email must not already be registered.
    """
    try:
        admin_user, tid = await add_tenant_admin(
            db=db,
            actor_user_id=current.user_id,
            tenant_id=tenant_id,
            email=body.email,
            password=body.password,
        )
    except TenantNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await db.commit()
    return AddAdminResponse(admin_user_id=admin_user.id, email=admin_user.email, tenant_id=tid)


@router.delete("/{tenant_id}/admins/{user_id}", response_model=RemoveAdminResponse)
async def remove_admin(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RemoveAdminResponse:
    """Remove a tenant_admin from a tenant.

    Deletes the membership only — the user account is preserved.
    Refuses to remove the last remaining admin of a tenant.
    """
    try:
        removed_id = await remove_tenant_admin(
            db=db,
            actor_user_id=current.user_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
    except LastAdminError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    except AdminNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    await db.commit()
    return RemoveAdminResponse(tenant_id=tenant_id, removed_user_id=removed_id)


# ---------------------------------------------------------------------------
# Platform manager management (manager-only)
# ---------------------------------------------------------------------------

@router.post("/managers", response_model=CreateManagerResponse, status_code=status.HTTP_201_CREATED)
async def create_manager(
    body: CreateManagerRequest,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CreateManagerResponse:
    """Create a new platform-level tenant_manager user.

    Only existing tenant_managers may call this.  The new manager has no
    tenant affiliation — their JWT carries role=tenant_manager with no tenant_id.
    """
    try:
        manager_user = await create_platform_manager(
            db=db,
            actor_user_id=current.user_id,
            email=body.email,
            password=body.password,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    await db.commit()
    return CreateManagerResponse(manager_user_id=manager_user.id, email=manager_user.email)


# ---------------------------------------------------------------------------
# Cost aggregate (manager-only, numeric summaries only)
# ---------------------------------------------------------------------------

@router.get("/{tenant_id}/cost")
async def get_tenant_cost(
    tenant_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate token + cost totals for a specific tenant.

    Returns numeric sums only — no conversation or content data.
    Note: manager routes do not go through tenant_scope / set_tenant_context.
    RLS is inactive for this session; correctness is guaranteed solely by the
    explicit WHERE clause inside aggregate_cost_for_tenant.
    """
    return await aggregate_cost_for_tenant(db=db, tenant_id=tenant_id, since=since, until=until)


@router.get("/cost/all")
async def get_all_tenants_cost(
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Aggregate cost totals for all tenants (manager dashboard)."""
    return await aggregate_cost_all_tenants(db=db, since=since, until=until)


# ---------------------------------------------------------------------------
# Audit log (manager-only)
# ---------------------------------------------------------------------------

@router.get("/{tenant_id}/audit")
async def get_audit(
    tenant_id: uuid.UUID,
    current: TenantManagerDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Fetch the audit log for a tenant.

    Returns structured action records — actor id, action, timestamp, metadata.
    Never returns tenant conversation or content data.
    """
    entries = await get_audit_log(
        db=db, target_tenant_id=tenant_id, limit=limit, offset=offset
    )
    return [
        {
            "id": str(e.id),
            "actor_user_id": str(e.actor_user_id),
            "action": e.action,
            "meta": e.meta,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]
