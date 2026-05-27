"""Widget admin service.

US2 lands ``rotate_signing_key``: mark the currently-active row inactive,
write fresh key material to Vault, INSERT the new row at ``version + 1`` and
``is_active=True`` — all inside a single Postgres TX that rolls back on
Vault failure. The response carries only ``(version, created_at)`` — never
the secret (FR-010b, data-model.md E2). The full admin surface (list_widgets,
create_widget, allowed_origins CRUD, guardrail config, embed snippet) lands
in US3.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import vault_client
from app.db.models.widget_signing_key_version import WidgetSigningKeyVersion

logger = logging.getLogger(__name__)


class SigningKeyRotationError(Exception):
    """Raised when key rotation fails. The TX is rolled back before raising."""


@dataclass(frozen=True)
class RotatedSigningKey:
    version: int
    created_at: datetime


_KEY_BYTES = 32


async def _current_active(
    session: AsyncSession, tenant_id: uuid.UUID
) -> WidgetSigningKeyVersion | None:
    result = await session.execute(
        select(WidgetSigningKeyVersion).where(
            WidgetSigningKeyVersion.tenant_id == tenant_id,
            WidgetSigningKeyVersion.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def _max_version(
    session: AsyncSession, tenant_id: uuid.UUID
) -> int:
    from sqlalchemy import func

    result = await session.execute(
        select(func.coalesce(func.max(WidgetSigningKeyVersion.version), 0)).where(
            WidgetSigningKeyVersion.tenant_id == tenant_id
        )
    )
    return int(result.scalar_one() or 0)


async def rotate_signing_key(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
) -> RotatedSigningKey:
    """Rotate the tenant's widget signing key. Atomic across Postgres + Vault.

    Steps:
      1. Mark the current active row inactive (set ``rotated_at``).
      2. Generate fresh random key material.
      3. Write the material to Vault. **Vault failure rolls back step 1.**
      4. INSERT a new ``is_active=True`` row at ``version + 1``.

    Returns metadata only — the response NEVER carries the secret (FR-010b).
    Side effect: invalidates every outstanding token for this tenant on the
    next chat call (T049 verifies this).
    """
    now = datetime.utcnow()

    current = await _current_active(session, tenant_id)
    if current is not None:
        current.is_active = False
        current.rotated_at = now
        await session.flush()

    next_version = await _max_version(session, tenant_id) + 1
    material = secrets.token_bytes(_KEY_BYTES)

    vault_version = await vault_client.write_tenant_widget_signing_key(
        tenant_id, material
    )
    if vault_version is None:
        # Vault write failed — roll back the Postgres TX so the previously
        # active row stays active. Outstanding tokens remain valid.
        await session.rollback()
        raise SigningKeyRotationError("vault write failed")

    new_row = WidgetSigningKeyVersion(
        tenant_id=tenant_id,
        version=next_version,
        is_active=True,
        created_at=now,
        created_by_user_id=actor_user_id,
    )
    session.add(new_row)
    await session.flush()

    logger.info(
        "widget_signing_key_rotated",
        extra={
            "event": "widget_signing_key_rotated",
            "version": next_version,
            # tenant_id intentionally omitted — raw tenant ids never logged
            # (FR-015c). actor_user_id is platform identity, not tenant.
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
        },
    )
    return RotatedSigningKey(version=next_version, created_at=now)
