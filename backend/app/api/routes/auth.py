"""Authentication routes: register, login, widget token exchange.

Security rules:
- tenant_id is NEVER accepted from the request body in any endpoint.
  It is resolved from the verified membership record after credentials check.
- Widget token exchange validates origin server-side (not just CORS).
  A curl with a copied widget_id and wrong origin gets a real 403.
- Passwords are bcrypt-hashed; never logged.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.auth.models import Role
from app.auth.users import (
    create_access_token,
    create_widget_token,
    hash_password,
    verify_password,
)
from app.db.models.membership import TenantMembership
from app.db.models.user import User
from app.db.models.widget_config import WidgetConfig
from app.db.session import get_db
from app.schemas.auth import CurrentUserResponse

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterResponse(BaseModel):
    user_id: uuid.UUID
    email: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class WidgetTokenRequest(BaseModel):
    widget_id: str
    origin: str


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    body: RegisterRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RegisterResponse:
    """Create a new user account.

    Does not assign a tenant or role — that is done by provisioning/invitation.
    """
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered.")

    user = User(
        id=uuid.uuid4(),
        email=body.email,
        hashed_password=hash_password(body.password),
        is_active=True,
    )
    db.add(user)
    await db.commit()
    return RegisterResponse(user_id=user.id, email=user.email)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Authenticate with email + password and return a signed JWT.

    The token embeds the user's role and tenant_id (if applicable) from the
    membership record — never from the request body.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active or not verify_password(body.password, user.hashed_password or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Resolve role and tenant_id from the membership table — never from body.
    # order_by created_at ensures deterministic result if multiple rows exist.
    membership_result = await db.execute(
        select(TenantMembership)
        .where(TenantMembership.user_id == user.id)
        .order_by(TenantMembership.created_at.asc())
    )
    membership = membership_result.scalars().first()

    role = Role(membership.role) if membership else Role.member
    tenant_id = membership.tenant_id if membership else None

    token = create_access_token(
        user_id=user.id,
        email=user.email,
        role=role,
        tenant_id=tenant_id,
    )
    return TokenResponse(access_token=token)


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=CurrentUserResponse)
async def me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> CurrentUserResponse:
    """Return the authenticated user's identity. 401 without a valid Bearer token."""
    return CurrentUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.platform_role,
        is_active=current_user.is_active,
    )


# ---------------------------------------------------------------------------
# Widget token exchange
# ---------------------------------------------------------------------------

@router.post("/widget-token", response_model=TokenResponse)
async def widget_token(
    body: WidgetTokenRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Exchange a public widget_id for a short-lived signed JWT.

    Validates:
      1. widget_id exists in widget_configs.
      2. The request origin is in the tenant's allowed_origins list (server-side,
         not just CORS — curl with a wrong origin gets a real 403).

    The returned token embeds tenant_id from the DB record — never from the body.
    CORS and CSP headers are additional layers set by middleware; this is the
    definitive auth check.
    """
    result = await db.execute(
        select(WidgetConfig).where(WidgetConfig.public_widget_id == body.widget_id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid widget_id.")

    # Server-side origin validation — CORS alone is insufficient.
    # An empty allowed_origins list is a misconfigured widget; block all origins
    # (secure default) rather than allowing all. The tenant admin must explicitly
    # add at least one allowed origin before the widget can issue tokens.
    allowed: list[str] = config.allowed_origins or []
    if not allowed or body.origin not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not permitted for this widget.",
        )

    token = create_widget_token(tenant_id=config.tenant_id, widget_id=body.widget_id)
    return TokenResponse(access_token=token)
