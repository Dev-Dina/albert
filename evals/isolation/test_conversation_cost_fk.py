"""Regression: widget/agent cost logging must not violate the conversations FK.

`cost_events.conversation_id` is an FK to `conversations.id`. The widget/chat flow
generates a conversation_id but never created the row, so the first agent cost
insert raised a ForeignKeyViolationError (→ 500). `ensure_conversation` creates the
row under the tenant's RLS context so the FK is satisfied.

Runs against a live Postgres under the real non-superuser runtime role
(``albert_app``) to faithfully reproduce the constraint + RLS behavior.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.cost import record_cost_event
from app.services.conversation import ensure_conversation
from app.tenancy.rls import set_tenant_context


async def _seed_tenant(db, tenant_id: uuid.UUID, slug_prefix: str) -> None:
    # Platform table insert as the connection's default (superuser) role.
    await db.execute(
        text(
            "INSERT INTO tenants (id, name, slug, status) "
            "VALUES (:t, 'FK Co', :s, 'active') ON CONFLICT (id) DO NOTHING"
        ),
        {"t": str(tenant_id), "s": f"{slug_prefix}-{tenant_id.hex[:8]}"},
    )


@pytest.mark.asyncio
async def test_ensure_conversation_lets_cost_event_link(db, tenant_a: uuid.UUID) -> None:
    """ensure_conversation + record_cost_event(conversation_id) under albert_app: no FK violation; both rows persist."""
    await _seed_tenant(db, tenant_a, "fk")
    await db.execute(text("SET ROLE albert_app"))
    try:
        await set_tenant_context(db, tenant_a)
        conv_id = uuid.uuid4()
        await ensure_conversation(db, tenant_a, conv_id)
        await record_cost_event(
            db=db,
            tenant_id=tenant_a,
            call_type="llm",
            model="gemini-2.5-flash-lite",
            input_tokens=10,
            output_tokens=5,
            conversation_id=conv_id,
        )
        conv_n = (
            await db.execute(text("SELECT count(*) FROM conversations WHERE id = :i"), {"i": str(conv_id)})
        ).scalar_one()
        cost_n = (
            await db.execute(
                text("SELECT count(*) FROM cost_events WHERE conversation_id = :i"), {"i": str(conv_id)}
            )
        ).scalar_one()
        assert conv_n == 1
        assert cost_n == 1
    finally:
        await db.rollback()
        await db.execute(text("RESET ROLE"))
        await db.rollback()


@pytest.mark.asyncio
async def test_ensure_conversation_is_idempotent(db, tenant_a: uuid.UUID) -> None:
    """Calling ensure_conversation twice for the same id is a safe no-op (multi-turn / races)."""
    await _seed_tenant(db, tenant_a, "fkidem")
    await db.execute(text("SET ROLE albert_app"))
    try:
        await set_tenant_context(db, tenant_a)
        conv_id = uuid.uuid4()
        await ensure_conversation(db, tenant_a, conv_id)
        await ensure_conversation(db, tenant_a, conv_id)
        n = (
            await db.execute(text("SELECT count(*) FROM conversations WHERE id = :i"), {"i": str(conv_id)})
        ).scalar_one()
        assert n == 1
    finally:
        await db.rollback()
        await db.execute(text("RESET ROLE"))
        await db.rollback()


@pytest.mark.asyncio
async def test_cost_event_fk_is_real_without_conversation(db, tenant_a: uuid.UUID) -> None:
    """Proof the FK is enforced: a cost event for a non-existent conversation raises (so ensure_conversation is required)."""
    await _seed_tenant(db, tenant_a, "fkraw")
    await db.execute(text("SET ROLE albert_app"))
    try:
        await set_tenant_context(db, tenant_a)
        with pytest.raises(IntegrityError):
            await record_cost_event(
                db=db,
                tenant_id=tenant_a,
                call_type="llm",
                model="m",
                conversation_id=uuid.uuid4(),  # no conversations row → FK violation
            )
    finally:
        await db.rollback()
        await db.execute(text("RESET ROLE"))
        await db.rollback()
