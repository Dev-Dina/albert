"""Tenant-admin widget routes (US3).

Every endpoint here is scoped to the caller's resolved tenant. The caller
must hold ``tenant_membership.role == 'tenant_admin'`` for that tenant —
the tenant id is derived from the membership row, NEVER from a request
body field (FR-009 mirror for admin routes).

Cross-tenant access (Tenant A admin asks about Tenant B's widget id)
returns 404, not 403 — per the OpenAPI contract, we do not confirm
existence of resources outside the caller's tenant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import Role
from app.auth.roles import CurrentUserDep
from app.db.models.membership import TenantMembership
from app.db.session import get_db
from app.schemas.admin_widget import (
    AdminWidget,
    AllowedOrigin,
    CreateAllowedOriginRequest,
    CreateWidgetRequest,
    EmbedSnippetResponse,
    FloorViolation as FloorViolationSchema,
    GuardrailConfig,
    SigningKeyVersionMetadata,
    UpdateWidgetRequest,
)
from app.services import widget_admin_service
from app.services.guardrail_floor import FloorViolation as FloorViolationExc

router = APIRouter(prefix="/api/v1/admin", tags=["admin-widgets"])


# ---------------------------------------------------------------------------
# Caller identity — (user_id, tenant_id) derived from membership
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AdminIdentity:
    user_id: uuid.UUID
    tenant_id: uuid.UUID


async def require_admin_identity(
    current: CurrentUserDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminIdentity:
    """Resolve (user_id, tenant_id) from the caller's tenant_admin membership.

    Fast paths:
      * If the JWT already carries role=tenant_admin AND a tenant_id claim,
        use those (covers the common path where Owner A issues a scoped
        token at login).
      * Otherwise look up the user's tenant_admin membership row.

    Refuses (403) if the caller is not a tenant_admin for some tenant. The
    response intentionally does not name which tenant.
    """
    if current.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated user required.",
        )

    if current.role == Role.tenant_admin and current.tenant_id is not None:
        return AdminIdentity(user_id=current.user_id, tenant_id=current.tenant_id)

    result = await db.execute(
        select(TenantMembership)
        .where(
            TenantMembership.user_id == current.user_id,
            TenantMembership.role == Role.tenant_admin.value,
        )
        .order_by(TenantMembership.created_at.asc())
    )
    membership = result.scalars().first()
    if membership is None or membership.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin role required.",
        )
    return AdminIdentity(user_id=current.user_id, tenant_id=membership.tenant_id)


AdminIdentityDep = Annotated[AdminIdentity, Depends(require_admin_identity)]


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

@router.get("/widgets", response_model=list[AdminWidget])
async def list_widgets(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AdminWidget]:
    widgets = await widget_admin_service.list_widgets(
        db, tenant_id=identity.tenant_id
    )
    return [
        AdminWidget(
            id=w.id,
            public_widget_id=w.public_widget_id,
            name=w.name,
            theme=w.theme or {},
            greeting=w.greeting or "",
            status=w.status,
        )
        for w in widgets
    ]


@router.post(
    "/widgets",
    response_model=AdminWidget,
    status_code=status.HTTP_201_CREATED,
)
async def create_widget(
    body: CreateWidgetRequest,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminWidget:
    widget = await widget_admin_service.create_widget(
        db,
        tenant_id=identity.tenant_id,
        name=body.name,
        greeting=body.greeting,
        theme=body.theme,
    )
    await db.commit()
    return AdminWidget(
        id=widget.id,
        public_widget_id=widget.public_widget_id,
        name=widget.name,
        theme=widget.theme or {},
        greeting=widget.greeting or "",
        status=widget.status,
    )


@router.patch("/widgets/{widget_id}", response_model=AdminWidget)
async def update_widget(
    widget_id: uuid.UUID,
    body: UpdateWidgetRequest,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminWidget:
    try:
        widget = await widget_admin_service.update_widget(
            db,
            tenant_id=identity.tenant_id,
            widget_id=widget_id,
            fields=body.model_dump(exclude_unset=True),
        )
    except widget_admin_service.WidgetNotFoundError as exc:
        # 404 not 403 — do not confirm existence of cross-tenant ids.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="widget not found"
        ) from exc
    await db.commit()
    return AdminWidget(
        id=widget.id,
        public_widget_id=widget.public_widget_id,
        name=widget.name,
        theme=widget.theme or {},
        greeting=widget.greeting or "",
        status=widget.status,
    )


@router.get(
    "/widgets/{widget_id}/embed-snippet",
    response_model=EmbedSnippetResponse,
)
async def get_embed_snippet(
    widget_id: uuid.UUID,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EmbedSnippetResponse:
    try:
        snippet = await widget_admin_service.embed_snippet(
            db, tenant_id=identity.tenant_id, widget_id=widget_id
        )
    except widget_admin_service.WidgetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="widget not found"
        ) from exc
    return EmbedSnippetResponse(
        snippet=snippet.snippet,
        loader_url=snippet.loader_url,
        data_widget_id=snippet.data_widget_id,
    )


# ---------------------------------------------------------------------------
# Allowed origins
# ---------------------------------------------------------------------------

@router.get("/allowed-origins", response_model=list[AllowedOrigin])
async def list_allowed_origins(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AllowedOrigin]:
    rows = await widget_admin_service.list_allowed_origins(
        db, tenant_id=identity.tenant_id
    )
    return [AllowedOrigin(id=r.id, origin=r.origin) for r in rows]


@router.post(
    "/allowed-origins",
    response_model=AllowedOrigin,
    status_code=status.HTTP_201_CREATED,
)
async def add_allowed_origin(
    body: CreateAllowedOriginRequest,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AllowedOrigin:
    row = await widget_admin_service.add_allowed_origin(
        db,
        tenant_id=identity.tenant_id,
        origin=body.origin,
        actor_user_id=identity.user_id,
    )
    await db.commit()
    return AllowedOrigin(id=row.id, origin=row.origin)


@router.delete(
    "/allowed-origins/{origin_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_allowed_origin(
    origin_id: uuid.UUID,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    removed = await widget_admin_service.remove_allowed_origin(
        db, origin_id=origin_id
    )
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="origin not found"
        )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Guardrail config — floor-enforced
# ---------------------------------------------------------------------------

@router.get("/guardrail-config", response_model=GuardrailConfig)
async def get_guardrail_config(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GuardrailConfig:
    cfg = await widget_admin_service.get_guardrail_config(
        db, tenant_id=identity.tenant_id
    )
    return GuardrailConfig(config=cfg)


@router.put("/guardrail-config", response_model=GuardrailConfig)
async def put_guardrail_config(
    body: GuardrailConfig,
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    try:
        cfg = await widget_admin_service.put_guardrail_config(
            db,
            tenant_id=identity.tenant_id,
            config=body.config,
            actor_user_id=identity.user_id,
        )
    except FloorViolationExc as exc:
        # 422 with the contract-specified body so the admin app can render
        # a precise message inline.
        payload = FloorViolationSchema(
            key_path=exc.key_path,
            attempted_value=exc.attempted_value,
            floor_value=exc.floor_value,
        )
        return Response(
            content=payload.model_dump_json(),
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            media_type="application/json",
        )
    await db.commit()
    return GuardrailConfig(config=cfg)


# ---------------------------------------------------------------------------
# Signing-key rotation
# ---------------------------------------------------------------------------

@router.get("/signing-key", response_model=SigningKeyVersionMetadata | None)
async def get_signing_key(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SigningKeyVersionMetadata | None:
    """Return the tenant's active signing key version + created_at.

    Metadata only — never returns the key material (FR-010b). Returns
    ``null`` for tenants that have not yet had a key minted (a tenant
    seeded via T043 always has v1; this null path is for safety).
    """
    meta = await widget_admin_service.get_active_signing_key_metadata(
        db, tenant_id=identity.tenant_id
    )
    if meta is None:
        return None
    return SigningKeyVersionMetadata(
        version=meta.version, created_at=meta.created_at
    )


@router.post(
    "/signing-key/rotate", response_model=SigningKeyVersionMetadata
)
async def rotate_signing_key(
    identity: AdminIdentityDep,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SigningKeyVersionMetadata:
    try:
        rotated = await widget_admin_service.rotate_signing_key(
            db,
            tenant_id=identity.tenant_id,
            actor_user_id=identity.user_id,
        )
    except widget_admin_service.SigningKeyRotationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="signing-key rotation failed",
        ) from exc
    await db.commit()
    return SigningKeyVersionMetadata(
        version=rotated.version, created_at=rotated.created_at
    )
