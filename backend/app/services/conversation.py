"""Conversation persistence helper.

A widget/chat ``conversation_id`` is generated client-side or server-side, but the
``conversations`` row was never created — so ``cost_events.conversation_id``
(FK → conversations.id) violated the foreign key the first time the agent logged a
cost. This helper idempotently ensures the row exists.

Must be called on a session whose RLS tenant context (``app.current_tenant``) is
already set to ``tenant_id`` (e.g. a ``get_tenant_db`` session). The INSERT's RLS
``WITH CHECK`` then enforces that the row is created for the caller's tenant only —
tenant_id comes from the verified token/session, never the request body.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def ensure_conversation(
    db: AsyncSession, tenant_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    """Idempotently create the conversations row for this tenant + conversation.

    No-op when it already exists (``ON CONFLICT (id) DO NOTHING``), so first-turn
    races and multi-turn chats are safe. Runs in the caller's transaction, so a
    same-transaction cost-event insert that references this id satisfies the FK.
    """
    await db.execute(
        text(
            "INSERT INTO conversations (id, tenant_id, session_id, status) "
            "VALUES (:id, :tid, :sid, 'open') "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(conversation_id), "tid": str(tenant_id), "sid": str(conversation_id)},
    )
