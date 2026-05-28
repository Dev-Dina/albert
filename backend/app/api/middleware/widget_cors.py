"""Per-tenant CORS for the widget API surface (T055a, FR-012, FR-015).

`fastapi.middleware.cors.CORSMiddleware` with a static origin list does not fit
this product: the allowlist is per-tenant and stored in the database, not in
config. This middleware leans on the server-side origin check (T054, in the
session route + T059a in the get_widget_session dep) as the trust boundary;
the ACAO header is emitted as DEFENSE-IN-DEPTH only after a widget route has
itself accepted the request.

Behavior:
- Non-widget paths: pass through untouched.
- Preflight (OPTIONS) to a widget endpoint: respond 204 with no ACAO. The
  browser will refuse the preflight, which is the correct outcome — the
  request will then never reach our route. (We cannot safely resolve a tenant
  in a preflight: there is no body and no Authorization token to derive the
  tenant identity from, and echoing an attacker's origin would be the very
  leak this middleware exists to prevent.)
- Non-preflight to a widget endpoint: forward to the route. If the route
  returns 2xx (i.e. the server-side origin check accepted the request), echo
  the Origin on Access-Control-Allow-Origin and append Origin to Vary. Any
  non-2xx response receives no ACAO header at all (FR-015: CORS is not the
  trust boundary; the server-side check is).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

_WIDGET_PATHS = frozenset(
    {
        "/api/v1/widget/session",
        "/api/v1/widget/chat",
    }
)


def _append_vary_origin(response: Response) -> None:
    """Add ``Origin`` to the ``Vary`` header without duplicating it."""
    existing = response.headers.get("vary")
    if existing is None:
        response.headers["Vary"] = "Origin"
        return
    if "origin" in existing.lower():
        return
    response.headers["Vary"] = f"{existing}, Origin"


class WidgetCorsMiddleware(BaseHTTPMiddleware):
    """Echo Origin on ACAO only after a widget route has accepted the request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path not in _WIDGET_PATHS:
            return await call_next(request)

        origin = request.headers.get("origin")

        if request.method == "OPTIONS":
            # Preflight: don't echo an unverified origin. Returning 204 with
            # no ACAO causes the browser to refuse the preflight, which is the
            # correct fail-closed behavior — the actual request never reaches
            # us, and tenant-side enforcement is preserved.
            return Response(status_code=204)

        response = await call_next(request)

        if origin and 200 <= response.status_code < 300:
            response.headers["Access-Control-Allow-Origin"] = origin
            _append_vary_origin(response)
        return response
