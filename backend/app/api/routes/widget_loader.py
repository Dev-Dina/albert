"""Widget loader + iframe page + bundle.

US2-hardened embed page: emits per-tenant
``Content-Security-Policy: frame-ancestors <allowlist>`` plus a legacy
``X-Frame-Options`` derived from the tenant's allowlist (FR-012). A widget
that is missing OR disabled OR whose tenant has no allowed origins returns 404
(no body leakage), matching the uniform-failure stance of the session route.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenant_context import tenant_context
from app.db.session import get_db
from app.repositories import allowed_origin_repo, widget_repo

router = APIRouter(tags=["widget-loader"])

_DIST_DIR = Path(__file__).resolve().parents[4] / "widget" / "dist"
_CSP_BASE = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "base-uri 'none'; "
    "form-action 'none'; "
)


def _build_csp(frame_ancestors: list[str]) -> str:
    """Build a CSP whose ``frame-ancestors`` directive is derived per-tenant.

    ``frame-ancestors`` is the ONLY effective control against iframe-in-iframe
    wrapping; the surrounding directives are constant across tenants.
    """
    ancestors = " ".join(frame_ancestors) if frame_ancestors else "'none'"
    return _CSP_BASE + f"frame-ancestors {ancestors}"


def _build_x_frame_options(frame_ancestors: list[str]) -> str:
    """Legacy header for older browsers.

    XFO can only express SAMEORIGIN or DENY (one origin max); with multiple
    allowed origins the modern CSP directive does the real work. We pick the
    safest representable answer here: DENY when no allowlist exists, otherwise
    SAMEORIGIN as a hint for ancient browsers.
    """
    return "SAMEORIGIN" if frame_ancestors else "DENY"


def _read_bundle_manifest() -> dict[str, str] | None:
    manifest_path = _DIST_DIR / "bundle-manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


@router.get("/widget.js")
async def get_widget_loader() -> Response:
    """Serve the built widget.js loader with a short cache."""
    loader_path = _DIST_DIR / "widget.js"
    if not loader_path.exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="widget bundle not built",
        )
    return Response(
        content=loader_path.read_bytes(),
        media_type="application/javascript; charset=utf-8",
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/widget/embed.html", response_class=HTMLResponse)
async def get_widget_embed(
    widget_id: str = Query(..., pattern=r"^[A-Za-z0-9]{22}$"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve the iframe HTML that bootstraps the React bundle.

    Resolves the tenant from the public widget_id and emits CSP
    ``frame-ancestors`` from the tenant's allowlist. Returns 404 for any
    failure (missing widget, disabled widget, no allowed origins) without
    leaking which case applied.
    """
    manifest = _read_bundle_manifest()
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="widget bundle not built",
        )

    # widget_repo.get_by_public_id uses a SECURITY DEFINER lookup (no tenant
    # context needed). The allowed-origins read below hits a tenant-scoped table
    # under FORCE ROW LEVEL SECURITY, so it must run with app.current_tenant set
    # to the resolved tenant — otherwise the non-superuser runtime role sees zero
    # rows and every embed wrongly 404s.
    lookup = await widget_repo.get_by_public_id(db, widget_id)
    if lookup is None or lookup.status != "enabled":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    async with tenant_context(db, lookup.tenant_id):
        origins_rows = await allowed_origin_repo.list_by_tenant(db, lookup.tenant_id)
    frame_ancestors = [row.origin for row in origins_rows]
    if not frame_ancestors:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    bundle_filename = manifest.get("filename", "")
    css_filename = manifest.get("css")
    css_link = (
        f"<link rel='stylesheet' href='/widget/{css_filename}'>" if css_filename else ""
    )
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Albert Widget</title>"
        f"{css_link}"
        "</head>"
        "<body><div id='root'></div>"
        f"<script type='module' src='/widget/{bundle_filename}'></script>"
        "</body></html>"
    )
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": _build_csp(frame_ancestors),
            "X-Frame-Options": _build_x_frame_options(frame_ancestors),
        },
    )


@router.get("/widget/{filename:path}")
async def get_widget_bundle(filename: str) -> Response:
    """Serve hashed bundle files with an immutable cache."""
    # Only allow bundle-*.{js,css} — no path traversal.
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if not filename.startswith("bundle-"):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if filename.endswith(".js"):
        media_type = "application/javascript; charset=utf-8"
    elif filename.endswith(".css"):
        media_type = "text/css; charset=utf-8"
    else:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    bundle_path = _DIST_DIR / filename
    if not bundle_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return Response(
        content=bundle_path.read_bytes(),
        media_type=media_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
