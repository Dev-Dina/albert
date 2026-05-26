"""Tenant-scoped widget guardrail config repository (one row per tenant)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.widget_guardrail_config import WidgetGuardrailConfig


async def get_for_tenant(
    session: AsyncSession, tenant_id: uuid.UUID
) -> WidgetGuardrailConfig | None:
    return (
        await session.execute(
            select(WidgetGuardrailConfig).where(
                WidgetGuardrailConfig.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()


async def upsert(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    updated_by_user_id: uuid.UUID | None = None,
) -> WidgetGuardrailConfig:
    existing = await get_for_tenant(session, tenant_id)
    if existing is None:
        row = WidgetGuardrailConfig(
            tenant_id=tenant_id,
            config=config,
            updated_by_user_id=updated_by_user_id,
        )
        session.add(row)
        await session.flush()
        return row
    existing.config = config
    existing.updated_by_user_id = updated_by_user_id
    await session.flush()
    return existing
