# Contract: `POST /api/v1/widget/session`

Token-exchange endpoint. Behavior **under Approach A** (this feature). Tenant
identity is derived solely from the server-side `widget_id` lookup; the request
body MUST NOT carry `tenant_id` (schema `extra='forbid'`).

## Request

- Headers: `Origin` (required), `Content-Type: application/json`.
- Body: `{ "widget_id": "<22-char base62>" }`.
- In the real browser flow the iframe is served from the backend origin, so
  `Origin` is the **backend** origin (same-origin request). This is expected and
  accepted — it is NOT compared against the customer allowlist.

## Behavior

1. If `Origin` header absent → **400** `{"detail":"Origin header required"}` (FR-009, fail closed).
2. Per-IP rate-limit gate (before DB work). If exceeded → **429** + `Retry-After`, body `{"detail":"rate_limited"}` (FR-014). MUST NOT name the dimension.
3. Resolve widget by `widget_id` (SECURITY DEFINER). If missing OR `status != enabled` → **403** `{"detail":"forbidden"}`.
4. Under the resolved tenant's RLS context: resolve active signing key version + Vault key material; hydrate public widget view. Any failure (no active key, no key material) → **403** `{"detail":"forbidden"}`.
5. ~~Compare `Origin` against the tenant's `widget_allowed_origins`.~~ **REMOVED in this feature.**
6. Mint signed token; per-tenant rate-limit gate (after resolve). If exceeded → **429** + `Retry-After`.
7. Success → **200** `{ session_token, expires_in, ttl_seconds, widget: { public_widget_id, theme, greeting } }`.

## Invariants (must hold; covered by tests)

- **C-S1 (FR-001)**: A request whose `Origin` is the backend origin and whose
  `widget_id` resolves to an enabled widget returns **200** with a token. *(This
  is the bug fix — previously 403.)*
- **C-S2 (FR-007, anti-enumeration)**: The 403 body is byte-identical across
  {unknown widget, disabled widget, missing/!active key, no key material}. It
  MUST NOT contain any of: `origin`, `allowlist`, `disabled`, `not found`,
  `widget`.
- **C-S3 (FR-002/FR-003)**: A body carrying `tenant_id` → **422** (schema
  rejects extra fields); tenant identity never read from the body.
- **C-S4 (FR-009)**: Missing `Origin` → **400**.
- **C-S5 (FR-014)**: Per-IP and per-tenant rate limits still return **429** with
  an opaque body and `Retry-After`.
- **C-S6**: The minted token's `org` claim equals the request `Origin`
  (informational; not re-validated downstream).

## Test deltas

- **CHANGED**: `test_widget_origin_csp.py::test_token_exchange_from_attacker_origin_returns_403_opaque_body`
  no longer applies (a non-allowlisted origin is no longer rejected at
  `/session`). Repurpose it to assert C-S1 (a non-allowlisted/backend origin now
  succeeds) and keep the companion unknown-widget 403 test for C-S2.
- **ADD**: success with `Origin == <backend origin>` (real browser flow, FR-012).
- **UNCHANGED**: `422` on body `tenant_id`; `400` on missing `Origin`; rate-limit tests.
