"""Tenant-admin escalations routes (feature 007, US3).

Read-only view of this tenant's escalated conversations with their captured
reason/summary. Scoped to the caller's resolved tenant via ``AdminIdentityDep``
(tenant id from the verified membership, never from body/query/path) plus RLS.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.admin_widgets import AdminIdentityDep
from app.db.session import get_db
from app.schemas.admin_escalations import EscalationResponse
from app.services import escalation_service as svc

router = APIRouter(prefix="/api/v1/admin/escalations", tags=["admin-escalations"])


def _to_response(escalation, conversation_status: str) -> EscalationResponse:
    return EscalationResponse(
        conversation_id=escalation.conversation_id,
        reason=escalation.reason,
        summary=escalation.summary,
        conversation_status=conversation_status,
        created_at=escalation.created_at,
        updated_at=escalation.updated_at,
    )


@router.get("", response_model=list[EscalationResponse])
async def list_escalations(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[EscalationResponse]:
    """List this tenant's escalated conversations (newest first)."""
    rows = await svc.list_escalations(
        db, tenant_id=identity.tenant_id, limit=limit, offset=offset
    )
    return [_to_response(esc, conv_status) for (esc, conv_status) in rows]


@router.get("/{conversation_id}", response_model=EscalationResponse)
async def get_escalation(
    conversation_id: uuid.UUID,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EscalationResponse:
    try:
        esc, conv_status = await svc.get_escalation(
            db, tenant_id=identity.tenant_id, conversation_id=conversation_id
        )
    except svc.EscalationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="escalation not found"
        ) from exc
    return _to_response(esc, conv_status)
