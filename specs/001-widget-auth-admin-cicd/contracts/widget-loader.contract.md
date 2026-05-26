# Contract: Widget Loader (`/widget.js`) and Iframe Bundle

This is not a JSON API; it is a browser-runtime contract. Implementations of the
loader and the iframe bundle MUST honor it byte-for-byte.

## `GET /widget.js`

**Response**:
- `Content-Type: application/javascript; charset=utf-8`
- `Cache-Control: public, max-age=60`
- Body: a small (≤ 4 KB minified) script that, on execution:
  1. Reads the currently-executing `<script>` tag.
  2. Reads its `data-widget-id` attribute.
  3. If missing / malformed (does not match `^[A-Za-z0-9]{22}$`): logs a clear
     `console.error("[albert-widget] data-widget-id is missing or invalid")`
     and returns without injecting anything (FR-005, **fail closed**).
  4. Else creates an `<iframe>` element pointing at
     `${SAME_ORIGIN}/widget/embed.html?widget_id=<id>`,
     positioned per a fixed default style, with `allow="clipboard-write"` and
     `sandbox="allow-scripts allow-same-origin allow-forms"`.
  5. Appends the iframe to `document.body`.

**The loader MUST NOT**:
- Call the token-exchange endpoint itself. That happens inside the iframe.
- Read or write any host-page state besides reading its own `<script>` tag.
- Fail silently for any reason.

## `GET /widget/embed.html?widget_id=<public_widget_id>`

**Response**:
- `Content-Type: text/html; charset=utf-8`
- `Cache-Control: no-store` (the page is tiny and per-widget; CSP and bundle sha
  are tenant-specific).
- `Content-Security-Policy:` derived from the tenant's allowlist:
  ```
  default-src 'none';
  script-src 'self';
  style-src 'self' 'unsafe-inline';
  connect-src 'self';
  img-src 'self' data:;
  frame-ancestors <origin1> <origin2> ...;
  base-uri 'none';
  form-action 'none';
  ```
- `X-Frame-Options:` legacy mirror of `frame-ancestors` for older crawlers.
- Body: minimal HTML that loads `/widget/bundle-<sha>.js` as a single `<script type="module">`.

**Behavior**:
- If the resolved widget is disabled, return **404** with an empty body. (Not 403:
  we do not confirm existence of widgets the embedder may not own.)
- If the resolved widget exists but the tenant has zero allowed origins, return
  the HTML with an empty `frame-ancestors 'none'` — browsers will block
  rendering. The admin app surfaces the "zero allowed origins" state separately
  (Edge Cases).

## `GET /widget/bundle-<sha>.js`

**Response**:
- `Content-Type: application/javascript; charset=utf-8`
- `Cache-Control: public, max-age=31536000, immutable`
- Body: the compiled widget bundle.

**Bundle runtime contract** (the iframe code):
1. On load, read `widget_id` from `location.search`.
2. POST `/api/v1/widget/session` with `{widget_id}`; the browser auto-attaches
   the `Origin` header.
3. On 200: store token + expiry in **iframe memory only** (no `localStorage`,
   no cookie); render chat UI with `widget.theme` + `widget.greeting`.
4. Schedule a silent re-exchange at `expires_in - 120` seconds (proactive,
   FR-008a).
5. On any chat call: include `Authorization: Bearer <token>`. On 401, attempt
   one silent re-exchange and retry the failed request once (FR-008b).
6. If silent re-exchange itself returns 403/429/4xx, render a non-technical
   "session expired — please refresh the page" state (FR-008b). Do **not**
   retry in a loop (FR-008c).

**The bundle MUST NOT**:
- Persist the session token in any storage that survives the iframe lifetime.
- Send a `tenant_id` field in any request body.
- Talk to any host page (no `postMessage` initiator without explicit feature
  scope, none in v1).
