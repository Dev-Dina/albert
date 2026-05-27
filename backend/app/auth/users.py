"""JWT authentication helpers.

Handles password hashing, access-token creation, and token decoding.
All secrets come from ``app.core.config.settings`` (sourced from Vault at
runtime), never from literals in this file.

Token payload convention:
  sub         — user id (UUID string)
  email       — user email
  role        — one of the three Role values
  tenant_id   — UUID string (absent for tenant_manager tokens)
  exp         — expiry (standard JWT claim)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.auth.models import Role
from app.core.config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---------------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------

def create_access_token(
    *,
    user_id: uuid.UUID,
    email: str,
    role: Role,
    tenant_id: uuid.UUID | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT for the given user.

    ``tenant_id`` must be None for tenant_manager tokens (they are platform-scoped).
    It must be present for tenant_admin and member tokens.
    """
    expire = datetime.now(UTC) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "email": email,
        "role": role.value,
        "exp": expire,
    }
    if tenant_id is not None:
        payload["tenant_id"] = str(tenant_id)

    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def create_widget_token(
    *,
    tenant_id: uuid.UUID,
    widget_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a short-lived signed token for widget visitor requests.

    The token binds a visitor session to exactly one tenant.  The widget_id
    is informational only; the tenant_id claim is what the API trusts.
    """
    expire = datetime.now(UTC) + (expires_delta or timedelta(minutes=30))
    payload: dict[str, Any] = {
        "sub": f"widget:{widget_id}",
        "tenant_id": str(tenant_id),
        "role": Role.member.value,
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


# ---------------------------------------------------------------------------
# Token decoding
# ---------------------------------------------------------------------------

def decode_access_token(token: str) -> dict[str, Any] | None:
    """Decode and verify a JWT.  Returns the payload dict or None on failure.

    Never raises — callers translate None into an appropriate HTTP error.
    Does not trust any claim without signature verification.
    """
    try:
        return jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError:
        return None


# ---------------------------------------------------------------------------
# Payload extractors (typed, safe)
# ---------------------------------------------------------------------------

def get_user_id(payload: dict[str, Any]) -> uuid.UUID | None:
    raw = payload.get("sub")
    if not raw or raw.startswith("widget:"):
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None


def get_role(payload: dict[str, Any]) -> Role | None:
    raw = payload.get("role")
    try:
        return Role(raw) if raw else None
    except ValueError:
        return None


def get_tenant_id(payload: dict[str, Any]) -> uuid.UUID | None:
    raw = payload.get("tenant_id")
    if not raw:
        return None
    try:
        return uuid.UUID(raw)
    except ValueError:
        return None
