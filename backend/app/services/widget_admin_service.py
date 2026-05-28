"""Widget admin service.

US2 lands ``rotate_signing_key``: mark the currently-active row inactive,
write fresh key material to Vault, INSERT the new row at ``version + 1`` and
``is_active=True`` — all inside a single Postgres TX that rolls back on
Vault failure. The response carries only ``(version, created_at)`` — never
the secret (FR-010b, data-model.md E2).

US3 extends this module with the full admin surface: list/create/update
widgets, list/add/remove allowed origins, get/put guardrail config (with
platform-floor enforcement), and an embed-snippet builder. Every call is
tenant-scoped by the caller's resolved membership; admins never pass a
``tenant_id`` field on the wire (FR-009 mirror for admin routes).
"""

from __future__ import annotations

import logging
import secrets
import string
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import vault_client
from app.core.config import settings
from app.db.models.widget import Widget
from app.db.models.widget_signing_key_version import WidgetSigningKeyVersion
from app.repositories import allowed_origin_repo, guardrail_config_repo, widget_repo
from app.services.guardrail_floor import FloorViolation, enforce_floor

logger = logging.getLogger(__name__)


class SigningKeyRotationError(Exception):
    """Raised when key rotation fails. The TX is rolled back before raising."""


class WidgetNotFoundError(Exception):
    """Caller asked for a widget that does not belong to their tenant."""


@dataclass(frozen=True)
class RotatedSigningKey:
    version: int
    created_at: datetime


@dataclass(frozen=True)
class EmbedSnippet:
    snippet: str
    loader_url: str
    data_widget_id: str


_KEY_BYTES = 32
_PUBLIC_ID_ALPHABET = string.ascii_letters + string.digits  # base62
_PUBLIC_ID_LEN = 22


def _generate_public_widget_id() -> str:
    return "".join(secrets.choice(_PUBLIC_ID_ALPHABET) for _ in range(_PUBLIC_ID_LEN))


# ---------------------------------------------------------------------------
# Signing-key rotation (US2 — unchanged)
# ---------------------------------------------------------------------------

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


async def get_active_signing_key_metadata(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> RotatedSigningKey | None:
    """Return the current active signing key's (version, created_at).

    Metadata only — never reads or returns the key material. Used by the
    admin app to show the current state on the Signing Key page so admins
    can verify they're on the expected version without rotating.
    """
    row = await _current_active(session, tenant_id)
    if row is None:
        return None
    return RotatedSigningKey(version=row.version, created_at=row.created_at)


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


# ---------------------------------------------------------------------------
# US3 — widget CRUD
# ---------------------------------------------------------------------------

async def list_widgets(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> list[Widget]:
    return await widget_repo.list_by_tenant(session, tenant_id)


async def create_widget(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    name: str,
    greeting: str = "",
    theme: dict[str, Any] | None = None,
) -> Widget:
    return await widget_repo.create(
        session,
        tenant_id=tenant_id,
        public_widget_id=_generate_public_widget_id(),
        name=name,
        theme=theme,
        greeting=greeting,
    )


async def _resolve_widget_for_tenant(
    session: AsyncSession,
    *,
    widget_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> Widget:
    widget = await widget_repo.get_by_id(session, widget_id)
    if widget is None or widget.tenant_id != tenant_id:
        # Per OpenAPI contract: do not confirm existence on cross-tenant ids.
        raise WidgetNotFoundError(str(widget_id))
    return widget


async def update_widget(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    widget_id: uuid.UUID,
    fields: dict[str, Any],
) -> Widget:
    widget = await _resolve_widget_for_tenant(
        session, widget_id=widget_id, tenant_id=tenant_id
    )
    allowed_fields = {"name", "greeting", "theme", "status"}
    cleaned = {k: v for k, v in fields.items() if k in allowed_fields and v is not None}
    if not cleaned:
        return widget
    return await widget_repo.update(session, widget, **cleaned)


def build_embed_snippet(public_widget_id: str) -> EmbedSnippet:
    """Render the copy-ready ``<script>`` snippet for a widget.

    The snippet is intentionally a single line so admins can paste it into
    the host site's HTML without manual editing (FR-018 / SC-001).
    """
    loader_url = settings.widget_loader_url
    snippet = (
        f'<script src="{loader_url}" data-widget-id="{public_widget_id}" async></script>'
    )
    return EmbedSnippet(
        snippet=snippet,
        loader_url=loader_url,
        data_widget_id=public_widget_id,
    )


async def embed_snippet(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    widget_id: uuid.UUID,
) -> EmbedSnippet:
    widget = await _resolve_widget_for_tenant(
        session, widget_id=widget_id, tenant_id=tenant_id
    )
    return build_embed_snippet(widget.public_widget_id)


# ---------------------------------------------------------------------------
# US3 — allowed origins
# ---------------------------------------------------------------------------

async def list_allowed_origins(
    session: AsyncSession, *, tenant_id: uuid.UUID
):
    return await allowed_origin_repo.list_by_tenant(session, tenant_id)


async def add_allowed_origin(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    origin: str,
    actor_user_id: uuid.UUID | None = None,
):
    return await allowed_origin_repo.add(
        session,
        tenant_id=tenant_id,
        origin=origin,
        created_by_user_id=actor_user_id,
    )


async def remove_allowed_origin(
    session: AsyncSession, *, origin_id: uuid.UUID
) -> bool:
    return await allowed_origin_repo.remove(session, origin_id)


# ---------------------------------------------------------------------------
# US3 — guardrail config (floor-enforced)
# ---------------------------------------------------------------------------

async def get_guardrail_config(
    session: AsyncSession, *, tenant_id: uuid.UUID
) -> dict[str, Any]:
    row = await guardrail_config_repo.get_for_tenant(session, tenant_id)
    if row is None:
        return {}
    return row.config or {}


async def put_guardrail_config(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    config: dict[str, Any],
    actor_user_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    # Raises FloorViolation on any weakening; the route translates that into
    # the 422 contract response with {key_path, attempted_value, floor_value}.
    enforce_floor(config)
    row = await guardrail_config_repo.upsert(
        session,
        tenant_id=tenant_id,
        config=config,
        updated_by_user_id=actor_user_id,
    )
    return row.config or {}


__all__ = [
    "EmbedSnippet",
    "FloorViolation",
    "RotatedSigningKey",
    "SigningKeyRotationError",
    "WidgetNotFoundError",
    "add_allowed_origin",
    "build_embed_snippet",
    "create_widget",
    "embed_snippet",
    "get_guardrail_config",
    "list_allowed_origins",
    "list_widgets",
    "put_guardrail_config",
    "remove_allowed_origin",
    "rotate_signing_key",
    "update_widget",
]
