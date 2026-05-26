"""Local widget preview server.

Serves the real built widget assets from widget/dist/ + a tiny demo host page,
and stubs POST /api/v1/widget/session and /chat so you can SEE the React UI
without standing up the docker stack.

Run:
    python scripts/widget_preview.py
Then open:
    http://localhost:8080/
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "widget" / "dist"
PORT = 8080

PUBLIC_WIDGET_ID = "Acm" + "P" * 19  # 22 chars
SIGNING_KEY = b"preview-signing-key-bytes-32-aaaa"
TENANT_ID = "11111111-1111-1111-1111-111111111111"
WIDGET_INTERNAL_ID = "22222222-2222-2222-2222-222222222222"
KEY_VERSION = 1
TTL_SECONDS = 900

GREETING = "Hi! I'm Albert, your demo assistant. Try saying hello!"
THEME = {"primary_color": "#2563eb"}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_hs256_token(claims: dict) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = (
        _b64url(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url(json.dumps(claims, separators=(",", ":")).encode())
    )
    sig = hmac.new(SIGNING_KEY, signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url(sig)


def _load_bundle_filename() -> str:
    manifest_path = DIST / "bundle-manifest.json"
    if not manifest_path.exists():
        return "bundle.tmp.js"
    return json.loads(manifest_path.read_text()).get("filename", "bundle.tmp.js")


HOST_PAGE = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>Albert Widget Preview</title>
    <style>
      body {{ font-family: system-ui, -apple-system, sans-serif; padding: 48px; line-height: 1.5; color: #1f2937; }}
      h1 {{ margin: 0 0 8px; }}
      .meta {{ color: #6b7280; font-size: 14px; margin-bottom: 32px; }}
      code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
    </style>
  </head>
  <body>
    <h1>Albert Widget — Live Preview</h1>
    <p class="meta">
      Host page on <code>http://localhost:{port}</code>.
      Look bottom-right → the widget iframe should be there.
    </p>
    <p>
      This page embeds the widget using:
      <br>
      <code>&lt;script src="/widget.js" data-widget-id="{wid}"&gt;&lt;/script&gt;</code>
    </p>
    <p>
      The session and chat endpoints are <strong>stubbed</strong> — the chat
      bot just echoes you back, but everything else (token mint, session
      memory, proactive re-exchange timer, React UI, theme, greeting) is the
      real built bundle.
    </p>
    <script src="/widget.js" data-widget-id="{wid}"></script>
  </body>
</html>
""".format(port=PORT, wid=PUBLIC_WIDGET_ID)


def _load_bundle_manifest() -> dict:
    manifest_path = DIST / "bundle-manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text())


def build_embed_html() -> str:
    manifest = _load_bundle_manifest()
    bundle = manifest.get("filename", "bundle.tmp.js")
    css = manifest.get("css")
    css_link = f'<link rel="stylesheet" href="/widget/{css}">' if css else ""
    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Albert Widget</title>
    {css_link}
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/widget/{bundle}"></script>
  </body>
</html>"""


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: A003 - silence default verbose logging
        print(f"[preview] {self.address_string()} - {fmt % args}")

    def _send_bytes(self, status: int, content_type: str, body: bytes, extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: dict) -> None:
        self._send_bytes(status, "application/json", json.dumps(payload).encode("utf-8"))

    # ----- GET -----
    def do_GET(self) -> None:  # noqa: N802 - http.server convention
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send_bytes(200, "text/html; charset=utf-8", HOST_PAGE.encode("utf-8"))
            return
        if path == "/widget.js":
            loader = (DIST / "widget.js").read_bytes()
            self._send_bytes(
                200,
                "application/javascript; charset=utf-8",
                loader,
                {"Cache-Control": "public, max-age=60"},
            )
            return
        if path == "/widget/embed.html":
            self._send_bytes(
                200,
                "text/html; charset=utf-8",
                build_embed_html().encode("utf-8"),
                {
                    "Cache-Control": "no-store",
                    "Content-Security-Policy": (
                        "default-src 'none'; script-src 'self'; "
                        "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                        "img-src 'self' data:; frame-ancestors 'self'; "
                        "base-uri 'none'; form-action 'none'"
                    ),
                    "X-Frame-Options": "SAMEORIGIN",
                },
            )
            return
        if path.startswith("/widget/") and (
            path.endswith(".js") or path.endswith(".css")
        ):
            name = path.removeprefix("/widget/")
            bundle = DIST / name
            if not bundle.exists():
                self.send_error(404)
                return
            ctype = (
                "application/javascript; charset=utf-8"
                if name.endswith(".js")
                else "text/css; charset=utf-8"
            )
            self._send_bytes(
                200,
                ctype,
                bundle.read_bytes(),
                {"Cache-Control": "public, max-age=31536000, immutable"},
            )
            return
        self.send_error(404)

    # ----- POST -----
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid_json"})
            return

        if self.path == "/api/v1/widget/session":
            origin = self.headers.get("Origin", "")
            now = int(time.time())
            claims = {
                "iss": "albert-preview",
                "sub": f"widget:{body.get('widget_id', PUBLIC_WIDGET_ID)}",
                "tnt": TENANT_ID,
                "wid": WIDGET_INTERNAL_ID,
                "kvr": KEY_VERSION,
                "org": origin,
                "iat": now,
                "exp": now + TTL_SECONDS,
            }
            token = mint_hs256_token(claims)
            self._send_json(
                200,
                {
                    "session_token": token,
                    "expires_in": TTL_SECONDS,
                    "ttl_seconds": TTL_SECONDS,
                    "widget": {
                        "public_widget_id": body.get("widget_id", PUBLIC_WIDGET_ID),
                        "theme": THEME,
                        "greeting": GREETING,
                    },
                },
            )
            return

        if self.path == "/api/v1/widget/chat":
            message = body.get("message", "")
            conversation_id = body.get("conversation_id") or str(secrets.token_hex(16))
            self._send_json(
                200,
                {
                    "conversation_id": conversation_id,
                    "message": f"You said: {message}",
                },
            )
            return

        self.send_error(404)


def main() -> None:
    if not (DIST / "widget.js").exists():
        raise SystemExit(
            "widget/dist/widget.js not found. Build first: cd widget && node esbuild.config.mjs"
        )
    print(f"[preview] serving on http://localhost:{PORT}/")
    print(f"[preview] bundle: {_load_bundle_filename()}")
    print(f"[preview] data-widget-id: {PUBLIC_WIDGET_ID}")
    print("[preview] Ctrl+C to stop.")
    ThreadingHTTPServer(("127.0.0.1", PORT), PreviewHandler).serve_forever()


if __name__ == "__main__":
    main()
