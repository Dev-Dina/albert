"""Request/trace correlation id (SPEC §9).

A ``request_id`` is generated at the backend edge when absent, or reused from an
inbound ``X-Request-ID`` header, and stored in a contextvar so downstream code
(e.g. the inference client) can propagate it to modelserver/guardrails. The id is
also echoed on the response.
"""

import re
import uuid
from collections.abc import Awaitable, Callable
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"

# Accept an inbound id only if it is a short, safe token — prevents header- and
# log-injection via a hostile X-Request-ID. Otherwise we mint a fresh one.
_SAFE_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")

_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


def get_request_id() -> str | None:
    """Return the current request's id, or None outside a request context."""
    return _request_id_var.get()


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate or propagate ``X-Request-ID`` and expose it via contextvar."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        inbound = request.headers.get(REQUEST_ID_HEADER)
        request_id = inbound if inbound and _SAFE_ID.match(inbound) else str(uuid.uuid4())
        token = _request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            _request_id_var.reset(token)
