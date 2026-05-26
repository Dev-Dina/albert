"""Service-to-service auth for the modelserver.

Verifies an ``Authorization: Bearer <token>`` header against ``SERVICE_AUTH_TOKEN``
read directly from the environment. Fails closed (401) on a missing, malformed,
or wrong token, or when no service token is configured. The token is never logged.
"""

import hmac
import os

from fastapi import Header, HTTPException, status

_BEARER_PREFIX = "Bearer "


def _unauthorized() -> HTTPException:
    """Return a fresh 401 (never a shared/module-level exception instance)."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="invalid service credential",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _expected_token() -> str:
    """Read the expected service token from the environment (never logged)."""
    return os.getenv("SERVICE_AUTH_TOKEN", "")


async def require_service_token(
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency: allow only requests bearing the service token.

    Fails closed: an unset ``SERVICE_AUTH_TOKEN``, a missing/malformed header,
    or a wrong token all raise 401.
    """
    expected = _expected_token()
    if not expected:
        raise _unauthorized()
    if authorization is None or not authorization.startswith(_BEARER_PREFIX):
        raise _unauthorized()
    presented = authorization[len(_BEARER_PREFIX) :]
    if not hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8")):
        raise _unauthorized()
