"""Audit log writer for platform-level (tenant_manager) actions.

Every privileged action that a tenant_manager takes — provision, suspend,
reactivate, erase, aggregate-cost read — must call ``record_audit`` so the
platform has an immutable trail with the actor id.

Rules:
- Never log secrets, tokens, passwords, or raw PII in the ``meta`` field.
- actor_user_id must always be present (no anonymous manager actions).
- This module is for platform actions only; tenant-level activity is out of scope.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


async def record_audit(
    *,
    db: AsyncSession,
    actor_user_id: uuid.UUID,
    action: str,
    target_tenant_id: uuid.UUID | None = None,
    meta: dict[str, Any] | None = None,
) -> AuditLog:
    """Insert an audit log row and flush (does not commit — caller owns the tx).

    Args:
        db:               Active async session.
        actor_user_id:    The tenant_manager performing the action.
        action:           Dot-namespaced action string, e.g. ``"tenant.provision"``.
        target_tenant_id: The tenant being acted upon, if applicable.
        meta:             Optional structured context.  MUST NOT contain secrets.

    Returns the persisted ``AuditLog`` row (id is available after flush).
    """
    entry = AuditLog(
        id=uuid.uuid4(),
        actor_user_id=actor_user_id,
        target_tenant_id=target_tenant_id,
        action=action,
        meta=meta or {},
    )
    db.add(entry)
    await db.flush()

    logger.info(
        "audit action=%s actor=%s target_tenant=%s",
        action,
        actor_user_id,
        target_tenant_id,
    )
    return entry


async def get_audit_log(
    *,
    db: AsyncSession,
    target_tenant_id: uuid.UUID,
    action_prefix: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[AuditLog]:
    """Fetch audit log entries for a specific tenant.

    ``target_tenant_id`` is required — omitting it would return the entire
    platform audit trail across all tenants.  Accessible by tenant_manager
    only (enforced at the route layer).
    Returns structured log rows — never tenant conversation or content data.
    """
    q = select(AuditLog).where(AuditLog.target_tenant_id == target_tenant_id).order_by(AuditLog.created_at.desc())
    if action_prefix is not None:
        q = q.where(AuditLog.action.startswith(action_prefix))
    q = q.limit(limit).offset(offset)

    result = await db.execute(q)
    return list(result.scalars().all())
