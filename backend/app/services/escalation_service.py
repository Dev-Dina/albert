"""Escalation read service for the tenant-admin view (feature 007, US3).

Tenant-scoped reads over ``escalation_repo``. The write path lives in the
``escalate`` tool (agent/chat flow), not here.
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.escalation import Escalation
from app.repositories import escalation_repo


class EscalationNotFoundError(Exception):
    """No escalation for this conversation in the caller's tenant (404)."""


async def list_escalations(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[tuple[Escalation, str]]:
    return await escalation_repo.list_for_tenant(
        session, tenant_id=tenant_id, limit=limit, offset=offset
    )


async def get_escalation(
    session: AsyncSession, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Escalation, str]:
    row = await escalation_repo.get_for_tenant(
        session, tenant_id=tenant_id, conversation_id=conversation_id
    )
    if row is None:
        raise EscalationNotFoundError(str(conversation_id))
    return row
