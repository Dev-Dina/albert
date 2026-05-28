"""Widget loader + iframe page + bundle (US1 baseline).

US2 layers in: per-tenant `Content-Security-Policy: frame-ancestors`,
`X-Frame-Options`, and 404 for disabled/missing widgets at the embed page.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["widget-loader"])

_DIST_DIR = Path(__file__).resolve().parents[4] / "widget" / "dist"
_PLACEHOLDER_CSP = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "img-src 'self' data:; "
    "frame-ancestors 'self'; "
    "base-uri 'none'; "
    "form-action 'none'"
)


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
) -> Response:
    """Serve the iframe HTML that bootstraps the React bundle.

    US1 baseline: placeholder CSP + 200 when manifest exists. US2 (T055) emits
    per-tenant `frame-ancestors` derived from the tenant's allowlist and 404
    when the resolved widget is disabled or missing.
    """
    manifest = _read_bundle_manifest()
    if manifest is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="widget bundle not built",
        )
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
            "Content-Security-Policy": _PLACEHOLDER_CSP,
            "X-Frame-Options": "SAMEORIGIN",
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
