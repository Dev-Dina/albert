# Phase 0 Research: Widget Cross-Origin Session & Chat Fix

All decisions below were either settled in `/speckit.clarify` (recorded in the
spec's Clarifications section) or are direct, low-risk consequences of Approach
A established here so that `/speckit.tasks` has no open unknowns.

## 1. Why removing the request-time origin check does NOT weaken tenant isolation

**Decision**: Stop comparing the request `Origin` against the customer
allowlist in both `widget_session_service.exchange()` and
`deps.get_widget_session()`.

**Rationale**:

- Tenant identity is derived from the **signed widget session token** (`tnt`
  claim) and, at exchange time, from the **server-side widget lookup** keyed by
  the public `widget_id`. Neither path ever read tenant identity from the
  request origin. The origin check was an *embedding/abuse* control, not an
  isolation control.
- RLS still scopes every tenant-owned read/write to the token's tenant via
  `tenant_context`. Removing the origin comparison changes nothing about which
  tenant context is set.
- The token signature (HS256 with the tenant's Vault-held key + key-version
  pinning) is what prevents a caller from acting as another tenant. An attacker
  who fabricates or replays a token for Tenant B cannot pass signature
  verification with Tenant B's key.

**Alternatives considered**:

- *Approach B (parent-origin exchange + CORS + postMessage)* — rejected in
  clarify: larger frontend+backend change; and `/chat` still runs from the
  backend-origin iframe, so it could not use the request `Origin` anyway.
- *Bind the customer origin into the token and re-check it* — rejected: under
  Approach A the exchange only sees the backend origin; obtaining the customer
  origin would require an untrusted client-supplied hint an attacker can spoof.

## 2. Fate of the per-tenant CORS middleware (`WidgetCorsMiddleware`)

**Decision**: **Remove** the middleware and its registration in `main.py`.

**Rationale**:

- The legitimate widget flow is **same-origin** to the backend (the iframe and
  the API share the backend origin), so it needs no `Access-Control-Allow-Origin`
  (ACAO) header at all.
- If the middleware were kept as-is after the allowlist check is removed,
  `/session` and `/chat` would return 2xx for cross-origin callers and the
  middleware would echo their `Origin` on ACAO — letting **any** website's
  JavaScript read a tenant's widget responses and build a working chat UI,
  fully bypassing the `frame-ancestors` embedding control. That is strictly
  worse than the accepted "scriptable via curl" posture (Q3), because it scales
  to every visitor of an attacker page.
- With the middleware gone, the browser's same-origin policy blocks
  cross-origin **reads** by default, and a cross-origin JSON `POST` triggers a
  preflight `OPTIONS` that now has no handler (405) — so cross-origin browser
  use is blocked, while non-browser clients (curl) remain able to call the
  public surface, exactly as Q3 accepted.

**Alternatives considered**:

- *Keep the middleware but stop echoing ACAO* — functionally identical for the
  legit same-origin flow but retains dead code; rejected for simplicity.
- *Add real per-tenant dynamic CORS* — only needed by Approach B; rejected.

**Consequence**: `test_widget_cors.py` is replaced (it asserted ACAO echo +
403-on-disallowed-origin, both of which no longer apply).

## 3. Keep the `Origin`-present gate and well-formed-origin check on `/session`

**Decision**: Keep `widget_session.py`'s `400 "Origin header required"` when the
header is absent, and keep `_origin_well_formed()` as input hygiene. Remove only
the allowlist comparison and its `"origin not allowed"` error.

**Rationale**: FR-009 mandates failing closed when no origin is present. Modern
browsers send `Origin` on same-origin `POST`, so the real flow is unaffected.
The well-formed check guards the value still minted into the token's
(informational) `org` claim. Neither is an isolation control; both are cheap
fail-closed hygiene.

**Alternatives considered**: Dropping the `Origin` requirement entirely —
rejected because the spec (FR-009) requires it and it costs nothing.

## 4. Mid-session revocation behavior (TTL-bounded)

**Decision** (from clarify): Removing an origin immediately blocks **new**
embeds via `frame-ancestors`; already-issued tokens remain valid until they
expire (session TTL, currently **900 s**). No per-request origin revocation.

**Rationale**: The `/chat` origin re-check that powered immediate revocation
(T059b/SC-008) is exactly the unreliable backend-origin check being removed.
Exposure is bounded by the short TTL; the TTL is configurable and can be
shortened if tighter revocation is later required (FR-017).

**Consequence**: `test_widget_origin_csp.py::test_chat_rejects_token_after_origin_removed_from_allowlist`
(T059b) is rewritten to assert the NEW behavior: chat still succeeds with a
valid unexpired token after the origin is removed, while `embed.html`'s
`frame-ancestors` no longer lists the removed origin (the embedding block).

## 5. Public chat surface posture (accepted)

**Decision** (from clarify): The chat API is an accepted public, rate-limited
surface keyed by the public `widget_id`. No additional request-time origin
control is added.

**Rationale**: A concierge widget is inherently public; `widget_id` is not a
secret. The three retained controls are sufficient: `frame-ancestors` (browser
embedding), the signed token (cross-tenant isolation), and the per-IP +
per-tenant token-bucket rate limits (abuse ceiling). These rate-limit gates in
`widget_session.py` are explicitly preserved (FR-014).

## 6. Frontend: no change required

**Decision**: Do not modify `widget/src` (loader, api, session, bootstrap).

**Rationale**: `loader.ts` correctly injects the iframe from the backend origin;
`api.ts` correctly uses relative URLs that resolve same-origin to the backend.
The browser was already producing the right request — the backend was wrongly
rejecting it. Fixing the backend fixes the end-to-end flow, keeping the PR small.

## 7. No migration / no config-schema change

**Decision**: No Alembic migration; no `config.py` edit.

**Rationale**: `widget_allowed_origins` is retained unchanged (it still drives
`frame-ancestors` and admin management). The TTL already exists in config at its
intended value. Avoiding migrations and `config.py` keeps the change off the
most sensitive protected files.

## 8. Local demo works after reverting the hack

**Decision**: Delete the manually added `http://localhost:8000` row from Acme's
`widget_allowed_origins`; no code/seed change.

**Rationale**: The demo host page runs at `http://localhost:8080` (seeded into
the allowlist), so `frame-ancestors` permits framing. The iframe's same-origin
`/session` + `/chat` calls succeed under Approach A regardless of the allowlist.
The `:8000` entry was only needed under the broken origin check and is now
unnecessary (FR-013).
