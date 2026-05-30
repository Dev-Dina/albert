"""Escalation read service for the tenant-admin view (feature 007, US3).

Tenant-scoped reads over ``escalation_repo``. The write path lives in the
``escalate`` tool (agent/chat flow), not here.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.escalation import Escalation
from app.repositories import escalation_repo
from app.services import escalation_lifecycle

logger = logging.getLogger(__name__)


class EscalationNotFoundError(Exception):
    """No escalation for this conversation in the caller's tenant (404)."""


class InvalidEscalationStatusError(Exception):
    """Requested status is not a valid escalation status (422)."""


async def list_escalations(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[tuple[Escalation, str]]:
    return await escalation_repo.list_for_tenant(
        session, tenant_id=tenant_id, status=status, limit=limit, offset=offset
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


async def set_escalation_status(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    new_status: str,
    resolved_by: uuid.UUID,
) -> tuple[Escalation, str]:
    """Resolve or reopen one escalation, scoped to the caller's tenant.

    Raises ``EscalationNotFoundError`` (404) if the conversation has no
    escalation in this tenant (covers cross-tenant attempts — no existence
    disclosure) or ``InvalidEscalationStatusError`` (422) on an invalid status.
    Does NOT change the conversation's own status (decoupled). Does not commit —
    the caller owns the transaction.
    """
    if not escalation_lifecycle.is_valid_status(new_status):
        raise InvalidEscalationStatusError(new_status)

    escalation, conversation_status = await get_escalation(
        session, tenant_id=tenant_id, conversation_id=conversation_id
    )
    await escalation_repo.set_status(
        session, escalation=escalation, status=new_status, resolved_by=resolved_by
    )
    logger.info(
        "escalation.status_changed tenant_id=%s conversation=%s status=%s actor=%s",
        tenant_id, conversation_id, new_status, resolved_by,
    )
    return escalation, conversation_status
