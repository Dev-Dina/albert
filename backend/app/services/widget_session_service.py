"""Widget session-token exchange service (US1 happy path).

US2 layers in: opaque-failure body, full origin parsing/validation, widget
status enforcement, and rate-limit wiring.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import vault_client
from app.core.config import settings
from app.core.security import WidgetTokenError, mint_widget_session_token
from app.db.models.widget_signing_key_version import WidgetSigningKeyVersion
from app.repositories import allowed_origin_repo, widget_repo
from app.schemas.widget import WidgetPublicView
from app.schemas.widget_session import WidgetSessionResponse


class WidgetSessionError(Exception):
    """Raised on any token-exchange failure (origin, widget, key, etc.)."""


@dataclass(frozen=True)
class _ResolvedWidget:
    widget_id: uuid.UUID
    tenant_id: uuid.UUID
    status: str


async def _fetch_active_key_version(
    session: AsyncSession, tenant_id: uuid.UUID
) -> WidgetSigningKeyVersion | None:
    result = await session.execute(
        select(WidgetSigningKeyVersion).where(
            WidgetSigningKeyVersion.tenant_id == tenant_id,
            WidgetSigningKeyVersion.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def exchange(
    session: AsyncSession,
    *,
    public_widget_id: str,
    origin: str,
) -> WidgetSessionResponse:
    """Resolve a public widget_id + origin to a signed widget session token.

    Tenant identity is taken SOLELY from the widget lookup; the caller never
    supplies tenant_id.
    """
    lookup = await widget_repo.get_by_public_id(session, public_widget_id)
    if lookup is None or lookup.status != "enabled":
        raise WidgetSessionError("widget not available")

    allowed = await allowed_origin_repo.exists_for_tenant(
        session, lookup.tenant_id, origin
    )
    if not allowed:
        raise WidgetSessionError("origin not allowed")

    active_key = await _fetch_active_key_version(session, lookup.tenant_id)
    if active_key is None:
        raise WidgetSessionError("no signing key")

    key_material = await vault_client.read_tenant_widget_signing_key(lookup.tenant_id)
    if key_material is None:
        raise WidgetSessionError("no signing key material")

    try:
        token = mint_widget_session_token(
            tenant_id=lookup.tenant_id,
            widget_id=lookup.widget_id,
            public_widget_id=public_widget_id,
            origin=origin,
            key_version=active_key.version,
            key_material=key_material,
        )
    except WidgetTokenError as exc:
        raise WidgetSessionError("token minting failed") from exc

    # Best-effort: hydrate the public widget view (theme/greeting) from the
    # widget row if the lookup helper gave us only the minimum fields.
    widget = await widget_repo.get_by_id(session, lookup.widget_id)
    public_view = (
        WidgetPublicView(
            public_widget_id=public_widget_id,
            theme=widget.theme if widget is not None else {},
            greeting=widget.greeting if widget is not None else "",
        )
        if True
        else None
    )

    return WidgetSessionResponse(
        session_token=token,
        expires_in=settings.widget_session_ttl_seconds,
        ttl_seconds=settings.widget_session_ttl_seconds,
        widget=public_view,
    )
