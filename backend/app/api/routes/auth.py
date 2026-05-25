from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.security import create_access_token, verify_password
from app.db.models.user import User
from app.db.session import get_db
from app.schemas.auth import CurrentUserResponse, LoginRequest, TokenResponse

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    """Authenticate an active user by email/password and return a Bearer token."""
    result = await db.execute(
        select(User).where(User.email == payload.email, User.is_active.is_(True))
    )
    user = result.scalar_one_or_none()
    if (
        user is None
        or user.hashed_password is None
        or not verify_password(payload.password, user.hashed_password)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    token = create_access_token(subject=str(user.id), role=user.platform_role or "")
    return TokenResponse(access_token=token)


@router.get("/me", response_model=CurrentUserResponse)
async def me(current_user: User = Depends(get_current_user)) -> CurrentUserResponse:
    """Return the authenticated user's identity."""
    return CurrentUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        role=current_user.platform_role,
        is_active=current_user.is_active,
    )
