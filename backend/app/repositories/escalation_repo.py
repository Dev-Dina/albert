"""Escalation repository — tenant-scoped persistence + reads (feature 007, US3).

One escalation row per conversation (1:1, FR-034). The write path (``upsert``) is
called from the ``escalate`` tool under the verified chat-session tenant context;
the read path serves the admin escalations view. Every query pins
``Escalation.tenant_id`` to the caller's tenant; RLS provides a second layer.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.conversation import Conversation
from app.db.models.escalation import Escalation


async def upsert(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    reason: str,
    summary: str = "",
) -> Escalation:
    """Insert the escalation, or update reason/summary/updated_at if one exists.

    Guarantees at most one row per conversation. Does not commit — the caller
    owns the transaction.
    """
    result = await session.execute(
        select(Escalation).where(
            Escalation.conversation_id == conversation_id,
            Escalation.tenant_id == tenant_id,
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.reason = reason
        existing.summary = summary
        existing.updated_at = datetime.now(timezone.utc)
        await session.flush()
        return existing

    escalation = Escalation(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        reason=reason,
        summary=summary,
    )
    session.add(escalation)
    await session.flush()
    return escalation


async def list_for_tenant(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 50,
    offset: int = 0,
) -> list[tuple[Escalation, str]]:
    """Return this tenant's escalations (newest updated_at first) with the
    joined conversation status, as ``[(escalation, conversation_status), ...]``."""
    query = (
        select(Escalation, Conversation.status)
        .join(Conversation, Conversation.id == Escalation.conversation_id)
        .where(Escalation.tenant_id == tenant_id)
        .order_by(Escalation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(query)
    return [(row[0], row[1]) for row in result.all()]


async def get_for_tenant(
    session: AsyncSession, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Escalation, str] | None:
    """Fetch one escalation (with conversation status) for this tenant, or None."""
    query = (
        select(Escalation, Conversation.status)
        .join(Conversation, Conversation.id == Escalation.conversation_id)
        .where(
            Escalation.tenant_id == tenant_id,
            Escalation.conversation_id == conversation_id,
        )
    )
    result = await session.execute(query)
    row = result.first()
    return (row[0], row[1]) if row is not None else None
