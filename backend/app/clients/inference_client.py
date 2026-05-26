"""Internal client helpers for calling Owner C services (modelserver, guardrails).

Phase 1 scope: provide the service-auth header and thin POST wrappers that attach
it. This module is **helper-only** — it is intentionally NOT wired into any route,
router, or agent yet. The service credential comes from
``settings.service_auth_token`` and is never logged.
"""

from typing import Any

import httpx

from app.core.config import settings
from app.core.request_context import get_request_id

_TIMEOUT = httpx.Timeout(10.0)
_REQUEST_ID_HEADER = "X-Request-ID"


def service_auth_headers() -> dict[str, str]:
    """Return the ``Authorization: Bearer <service credential>`` header.

    The credential is read from ``settings.service_auth_token``; it is never logged.
    """
    token = settings.service_auth_token.get_secret_value()
    return {"Authorization": f"Bearer {token}"}


def _outbound_headers() -> dict[str, str]:
    """Service-auth header plus the propagated ``X-Request-ID`` when one is set."""
    headers = service_auth_headers()
    request_id = get_request_id()
    if request_id:
        headers[_REQUEST_ID_HEADER] = request_id
    return headers


async def _post(base_url: str, path: str, payload: dict[str, Any]) -> httpx.Response:
    """POST ``payload`` to ``base_url + path`` with auth + request-id headers."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        return await client.post(
            f"{base_url}{path}", json=payload, headers=_outbound_headers()
        )


async def call_modelserver_predict(payload: dict[str, Any]) -> httpx.Response:
    """POST to the modelserver ``/predict`` endpoint with the service token."""
    return await _post(settings.modelserver_url, "/predict", payload)


async def call_guardrails_check_input(payload: dict[str, Any]) -> httpx.Response:
    """POST to the guardrails ``/check-input`` endpoint with the service token."""
    return await _post(settings.guardrails_url, "/check-input", payload)


async def call_guardrails_check_output(payload: dict[str, Any]) -> httpx.Response:
    """POST to the guardrails ``/check-output`` endpoint with the service token."""
    return await _post(settings.guardrails_url, "/check-output", payload)
