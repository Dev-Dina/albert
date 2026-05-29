"""Authentication routes.

User-login auth is handled by **fastapi-users** (JWT email/password). This module
exposes a thin JSON ``/auth/login`` compatibility adapter that delegates credential
verification + token issuance to the fastapi-users ``UserManager`` and JWT strategy —
no hand-rolled hashing or token logic remains here.

Account creation is provisioning-only (no public registration). Widget visitors use
a separate signed widget-session token (``/api/v1/widget/session``), not this module.

Security: a login token carries only the user id. Role + tenant are resolved
server-side from the database per request — never from the token or request body.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from app.auth.fastapi_users import UserManager, auth_backend, current_active_user, get_user_manager
from app.db.models.user import User
from app.ratelimit import check_auth_rate_limit
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])

_invalid_credentials = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials.",
    headers={"WWW-Authenticate": "Bearer"},
)


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    user_manager: Annotated[UserManager, Depends(get_user_manager)],
    _rl: Annotated[None, Depends(check_auth_rate_limit)],
) -> TokenResponse:
    """Authenticate with email + password and return a fastapi-users JWT.

    JSON compatibility wrapper: credential check + token issuance are performed
    by fastapi-users (``UserManager.authenticate`` + the JWT strategy).
    """
    credentials = OAuth2PasswordRequestForm(username=body.email, password=body.password)
    user = await user_manager.authenticate(credentials)
    if user is None or not user.is_active:
        raise _invalid_credentials

    token = await auth_backend.get_strategy().write_token(user)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CurrentUserResponse)
async def me(
    current_user: Annotated[User, Depends(current_active_user)],
) -> CurrentUserResponse:
    """Return the authenticated user's identity. 401 without a valid Bearer token."""
    return CurrentUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.platform_role,
        is_active=current_user.is_active,
    )
