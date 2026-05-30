import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.roles import CurrentUser, get_current_user
from app.clients import vault_client
from app.core.security import (
    WidgetSessionClaims,
    WidgetTokenError,
    verify_widget_session_token,
)
from app.core.tenant_context import tenant_context
from app.db.models.widget_signing_key_version import WidgetSigningKeyVersion
from app.db.session import get_db
from app.tenancy.status import is_tenant_active


async def get_admin_tenant_id(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> str:
    """Return the tenant_id for the authenticated tenant-scoped user.

    Resolved from ``tenant_memberships`` via the verified principal — never from
    a client-supplied body. Platform managers (no tenant) are refused 403.
    """
    if current.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context required; platform managers have no tenant content access.",
        )
    return str(current.tenant_id)


_widget_credentials_exc = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate widget session",
    headers={"WWW-Authenticate": "Bearer"},
)


def _read_bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _widget_credentials_exc
    return token


async def _fetch_active_key_version(
    db: AsyncSession, tenant_id: uuid.UUID
) -> WidgetSigningKeyVersion | None:
    result = await db.execute(
        select(WidgetSigningKeyVersion).where(
            WidgetSigningKeyVersion.tenant_id == tenant_id,
            WidgetSigningKeyVersion.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_widget_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AsyncIterator[WidgetSessionClaims]:
    """Resolve a widget visitor's verified session claims.

    Sets ``app.current_tenant`` on the request's DB session so all subsequent
    tenant-scoped queries are gated by RLS for the lifetime of the request.
    Returns 401 on any failure; NEVER leaks why (signature mismatch vs.
    expiry vs. rotation).

    Approach A (feature 006): the request Origin is NOT re-checked against the
    customer allowlist. Tenant identity comes solely from the verified token;
    the allowlist governs embedding only (the per-tenant ``frame-ancestors`` CSP
    on ``embed.html``). Mid-session allowlist changes are TTL-bounded — an
    already-issued token keeps authorizing chat until it expires.
    """
    token = _read_bearer(request)

    # Parse-only first pass to learn (tenant_id, kvr). Signature check happens
    # below with the resolved key material.
    try:
        from jose import jwt

        unverified = jwt.get_unverified_claims(token)
        tenant_id = uuid.UUID(str(unverified["tnt"]))
        kvr_claim = int(unverified["kvr"])
    except (JWTError, KeyError, ValueError, TypeError) as exc:
        raise _widget_credentials_exc from exc

    # The signing-key-version read below hits tenant-scoped tables under FORCE
    # ROW LEVEL SECURITY. The runtime role is non-superuser / NOBYPASSRLS, so it
    # must run with app.current_tenant set or RLS filters every row (→ spurious
    # 401). Scope to the token-claimed tenant: an attacker claiming another
    # tenant only loads THAT tenant's key and fails signature verification below,
    # so this is safe and leaks nothing cross-tenant. The context stays set
    # through the yield so the request runs tenant-scoped.
    async with tenant_context(db, tenant_id):
        active = await _fetch_active_key_version(db, tenant_id)
        if active is None or active.version != kvr_claim:
            raise _widget_credentials_exc

        key_material = await vault_client.read_tenant_widget_signing_key(tenant_id)
        if key_material is None:
            raise _widget_credentials_exc

        try:
            claims = verify_widget_session_token(
                token,
                key_material=key_material,
                expected_key_version=active.version,
            )
        except WidgetTokenError as exc:
            raise _widget_credentials_exc from exc

        # Tenant status gate: refuse chat for a non-active (suspended/erased) tenant,
        # even with an already-issued, still-valid token. Reuses the generic widget 401
        # so it discloses nothing (no suspended-vs-erased-vs-missing distinction).
        # ``tenants`` has no RLS, so this read is unaffected by the tenant context.
        if not await is_tenant_active(db, tenant_id):
            raise _widget_credentials_exc

        # Approach A: no request-Origin re-check. The token's ``org`` claim is
        # informational only; tenant identity is the verified ``tnt`` claim. The
        # request runs under the token's tenant context for the lifetime of the
        # yield.
        yield claims
