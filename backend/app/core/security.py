"""Widget-session token security.

This module is dedicated to the **widget visitor** auth system: short-lived,
per-tenant HS256-signed session tokens minted/verified with the tenant's own
signing-key material (from Vault), not the platform JWT secret. It is entirely
separate from user-login auth, which is handled by fastapi-users
(``app/auth/fastapi_users.py``). Plaintext, key material, and tokens are never logged.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

# python-jose is used ONLY for widget-session tokens (HS256 + per-tenant key
# material) in this module — never for user-login auth, which is fastapi-users.
from jose import jwt
from jose.exceptions import JWTError

from app.core.config import settings

_WIDGET_TOKEN_ALG = "HS256"


def decode_access_token(token: str) -> dict:
    """Decode and validate a JWT. Raises jose.JWTError if invalid or expired.

    Used by widget-session path (api/deps.py) which expects the exception-raising
    contract. Standard tenant routes use app.auth.users.decode_access_token which
    returns None on failure instead.
    """
    return jwt.decode(
        token, settings.jwt_secret.get_secret_value(), algorithms=[settings.jwt_algorithm]
    )


@dataclass(frozen=True)
class WidgetSessionClaims:
    """Verified claims extracted from a widget session token (data-model.md E5)."""

    tenant_id: uuid.UUID
    widget_id: uuid.UUID
    public_widget_id: str
    key_version: int
    origin: str
    issued_at: int
    expires_at: int


class WidgetTokenError(Exception):
    """Raised for any widget-session-token verification failure."""


def mint_widget_session_token(
    *,
    tenant_id: uuid.UUID,
    widget_id: uuid.UUID,
    public_widget_id: str,
    origin: str,
    key_version: int,
    key_material: bytes,
) -> str:
    """Sign and return an HS256 widget session JWT (data-model.md E5).

    Key material is the per-tenant signing key; never the platform JWT secret.
    """
    if not key_material:
        raise WidgetTokenError("missing key material")
    now = datetime.now(UTC)
    iat = int(now.timestamp())
    exp = int(
        (now + timedelta(seconds=settings.widget_session_ttl_seconds)).timestamp()
    )
    claims = {
        "iss": "albert",
        "sub": f"widget:{public_widget_id}",
        "tnt": str(tenant_id),
        "wid": str(widget_id),
        "kvr": int(key_version),
        "org": origin,
        "iat": iat,
        "exp": exp,
    }
    return jwt.encode(claims, key_material, algorithm=_WIDGET_TOKEN_ALG)


def verify_widget_session_token(
    token: str,
    key_material: bytes,
    expected_key_version: int,
) -> WidgetSessionClaims:
    """Verify an HS256 widget session JWT against the tenant's active key.

    Allows ±widget_clock_skew_seconds of clock skew on ``exp``. Raises
    :class:`WidgetTokenError` for any failure (signature, expiry, key rotation,
    malformed claims). Callers translate this to HTTP 401.
    """
    if not token or not key_material:
        raise WidgetTokenError("missing token or key material")
    try:
        payload = jwt.decode(
            token,
            key_material,
            algorithms=[_WIDGET_TOKEN_ALG],
            options={"verify_aud": False, "verify_exp": False},
        )
    except JWTError as exc:
        raise WidgetTokenError("invalid signature") from exc

    try:
        tenant_id = uuid.UUID(str(payload["tnt"]))
        widget_id = uuid.UUID(str(payload["wid"]))
        key_version = int(payload["kvr"])
        origin = str(payload["org"])
        iat = int(payload["iat"])
        exp = int(payload["exp"])
        subject = str(payload.get("sub", ""))
    except (KeyError, ValueError, TypeError) as exc:
        raise WidgetTokenError("malformed claims") from exc

    if key_version != expected_key_version:
        raise WidgetTokenError("key rotated")

    skew = settings.widget_clock_skew_seconds
    now = int(datetime.now(UTC).timestamp())
    if now > exp + skew:
        raise WidgetTokenError("expired")

    public_widget_id = subject.removeprefix("widget:") if subject else ""
    return WidgetSessionClaims(
        tenant_id=tenant_id,
        widget_id=widget_id,
        public_widget_id=public_widget_id,
        key_version=key_version,
        origin=origin,
        issued_at=iat,
        expires_at=exp,
    )
