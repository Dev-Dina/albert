"""Tenant-admin leads + members routes (FR-050 exception 1).

Every endpoint is scoped to the caller's resolved tenant via the existing
``AdminIdentity`` dependency — the tenant id derives from the verified
``tenant_admin`` membership, NEVER from a request body, query string, or path.
The Members endpoints manage only ``role='member'`` rows; ``tenant_admin`` rows
belong to the manager surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.admin_widgets import AdminIdentityDep
from app.db.session import get_db
from app.schemas.admin_members_and_leads import (
    LeadResponse,
    MemberInviteRequest,
    MemberRemoveResponse,
    MemberResponse,
)
from app.services import admin_members_leads_service as svc

router = APIRouter(prefix="/api/v1/admin", tags=["admin-members-leads"])


# ---------------------------------------------------------------------------
# Leads (read-only)
# ---------------------------------------------------------------------------

@router.get("/leads", response_model=list[LeadResponse])
async def list_leads(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    since: datetime | None = None,
    until: datetime | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[LeadResponse]:
    """List this tenant's leads (newest first). Scoped to the caller's tenant."""
    leads = await svc.list_leads(
        db,
        tenant_id=identity.tenant_id,
        since=since,
        until=until,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return [
        LeadResponse(
            id=lead.id,
            name=lead.name,
            contact=lead.contact,
            intent=lead.intent,
            status=lead.status,
            created_at=lead.created_at,
            conversation_id=lead.conversation_id,
        )
        for lead in leads
    ]


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

@router.get("/members", response_model=list[MemberResponse])
async def list_members(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[MemberResponse]:
    """List this tenant's ``role='member'`` rows. Scoped to the caller's tenant."""
    rows = await svc.list_members(
        db, tenant_id=identity.tenant_id, limit=limit, offset=offset
    )
    return [
        MemberResponse(
            user_id=membership.user_id,
            email=email,
            created_at=membership.created_at,
        )
        for (membership, email) in rows
    ]


@router.post(
    "/members",
    response_model=MemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_member(
    body: MemberInviteRequest,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MemberResponse:
    """Invite a new member to this tenant (create user + membership atomically)."""
    try:
        user, membership = await svc.invite_member(
            db,
            actor_user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            email=body.email,
            password=body.password,
        )
    except svc.EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    await db.commit()
    return MemberResponse(
        user_id=user.id, email=user.email, created_at=membership.created_at
    )


@router.delete("/members/{user_id}", response_model=MemberRemoveResponse)
async def remove_member(
    user_id: uuid.UUID,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MemberRemoveResponse:
    """Remove a member from this tenant. Cannot remove self; preserves the user row."""
    try:
        removed_id = await svc.remove_member(
            db,
            actor_user_id=identity.user_id,
            tenant_id=identity.tenant_id,
            user_id=user_id,
        )
    except svc.CannotRemoveSelfError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except svc.MemberNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    await db.commit()
    return MemberRemoveResponse(
        tenant_id=identity.tenant_id, removed_user_id=removed_id
    )
