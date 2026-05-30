"""Widget session-token exchange service.

Approach A (feature 006): the customer allowlist is decoupled from the
request-time origin check. Tenant identity is derived solely from the
server-side ``widget_id`` lookup, so the request Origin is NOT compared against
``widget_allowed_origins`` here — that table governs embedding only (the
per-tenant ``frame-ancestors`` CSP on ``embed.html``). A well-formed-Origin
gate is retained (fail-closed), but a backend/non-allowlisted origin now
succeeds.

US2-hardened: every remaining failure path raises ``WidgetSessionError`` which
the route translates to a single uniform 403 response body, so callers cannot
tell "widget not found" from "widget disabled" from "no signing key" (FR-013,
prevents enumeration). The well-formed-Origin check, widget status check, and
signing-key resolution all collapse to the same error.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import vault_client
from app.core.config import settings
from app.core.security import WidgetTokenError, mint_widget_session_token
from app.core.tenant_context import tenant_context
from app.db.models.widget_signing_key_version import WidgetSigningKeyVersion
from app.repositories import widget_repo
from app.schemas.widget import WidgetPublicView
from app.schemas.widget_session import WidgetSessionResponse
from app.tenancy.status import is_tenant_active


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


def _origin_well_formed(origin: str) -> bool:
    """Reject obviously-malformed Origin headers before any DB lookup.

    Browsers send `scheme://host[:port]` with no path/query/fragment. We accept
    only http/https; anything else short-circuits to the uniform 403.
    """
    if not origin or origin == "null":
        return False
    lowered = origin.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    # No path/query/fragment in an Origin header (after the scheme).
    tail = origin.split("://", 1)[1]
    if any(ch in tail for ch in "/?#"):
        return False
    return True


async def exchange(
    session: AsyncSession,
    *,
    public_widget_id: str,
    origin: str,
) -> WidgetSessionResponse:
    """Resolve a public widget_id + origin to a signed widget session token.

    Tenant identity is taken SOLELY from the widget lookup; the caller never
    supplies tenant_id. All failure modes raise ``WidgetSessionError`` which
    the route turns into a uniform 403 (FR-013).
    """
    if not _origin_well_formed(origin):
        raise WidgetSessionError("malformed origin")

    # Resolve tenant identity via the SECURITY DEFINER lookup, which runs with no
    # tenant context (the public endpoint has none yet).
    lookup = await widget_repo.get_by_public_id(session, public_widget_id)
    if lookup is None or lookup.status != "enabled":
        raise WidgetSessionError("widget not available")

    # Tenant status gate: refuse a non-active (suspended/erased) tenant before minting a
    # session. Collapses into the route's uniform 403 (no enumeration / no new leak).
    # ``tenants`` has no RLS, so this read needs no tenant context.
    if not await is_tenant_active(session, lookup.tenant_id):
        raise WidgetSessionError("tenant not active")

    # The remaining reads hit tenant-scoped tables (widget_allowed_origins,
    # widget_signing_key_versions, widgets) under FORCE ROW LEVEL SECURITY. The
    # runtime role is non-superuser / NOBYPASSRLS, so without app.current_tenant
    # set RLS filters every row and exchange would wrongly 403. Set the context
    # to the tenant just resolved from the trusted lookup (never from the caller).
    async with tenant_context(session, lookup.tenant_id):
        # Approach A: the request Origin is NOT compared against
        # widget_allowed_origins here. That allowlist governs embedding only
        # (frame-ancestors on embed.html); tenant identity already comes from
        # the trusted widget lookup above.
        active_key = await _fetch_active_key_version(session, lookup.tenant_id)
        if active_key is None:
            raise WidgetSessionError("no signing key")

        # Hydrate the public widget view (theme/greeting) while under context.
        widget = await widget_repo.get_by_id(session, lookup.widget_id)

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

    public_view = WidgetPublicView(
        public_widget_id=public_widget_id,
        theme=widget.theme if widget is not None else {},
        greeting=widget.greeting if widget is not None else "",
    )

    return WidgetSessionResponse(
        session_token=token,
        expires_in=settings.widget_session_ttl_seconds,
        ttl_seconds=settings.widget_session_ttl_seconds,
        widget=public_view,
    )
