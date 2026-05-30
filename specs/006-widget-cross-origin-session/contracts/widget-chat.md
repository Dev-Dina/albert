# Contract: `POST /api/v1/widget/chat`

Visitor chat surface. Tenant identity comes exclusively from the verified token
claims (`get_widget_session` dependency). Behavior **under Approach A**.

## Request

- Headers: `Authorization: Bearer <widget session token>` (required).
  `Origin` MAY be present (the backend origin in the real flow) but is **not**
  inspected.
- Body: `{ "message": "...", "conversation_id"?: "<uuid>" }`. Any `tenant_id` in
  the body is ignored and logged as a hashed event (never trusted).

## `get_widget_session` dependency behavior

1. Read bearer token; absent/malformed scheme → **401** (uniform).
2. Parse unverified claims to learn (`tnt`, `kvr`). Malformed → **401**.
3. Under the token-claimed tenant's RLS context: load active signing key
   version; if absent or `version != kvr` → **401**. Load Vault key material;
   absent → **401**.
4. Verify token signature + expiry against the key material; failure → **401**.
5. ~~Require request `Origin` present and ∈ tenant allowlist.~~ **REMOVED in this feature.**
6. Yield `WidgetSessionClaims`; the request runs under the token's tenant context.

## Behavior (route, unchanged by this feature)

- Guardrails input check → router/workflow → agent/RAG → guardrails output check.
- Empty-reply fallback and controlled 503s on provider errors remain as-is.
- Success → **200** `{ conversation_id, message }`.

## Invariants (must hold; covered by tests)

- **C-C1 (FR-001)**: A valid unexpired token authorizes chat regardless of the
  request `Origin` (real browser flow sends the backend origin). *(Bug fix.)*
- **C-C2 (FR-003, isolation)**: A token issued for Tenant A only ever runs under
  Tenant A's context; replies/side-effects are Tenant-A-scoped. A token signed
  with the wrong key, an expired token, or a token whose `kvr` is inactive →
  **401**.
- **C-C3 (FR-006/FR-017, TTL-bounded revocation)**: After an admin removes the
  origin from the allowlist, a still-valid token continues to authorize chat
  (**200**) until it expires. Immediate revocation is NOT expected on `/chat`;
  embedding is blocked at `embed.html` instead.
- **C-C4 (FR-008, anti-enumeration)**: All auth failures return a uniform
  **401** with `WWW-Authenticate: Bearer` and a single opaque detail; the cause
  (signature vs expiry vs rotation) is never disclosed.
- **C-C5 (FR-002)**: A `tenant_id` in the body is ignored; tenant identity is the
  token's `tnt`.

## Test deltas

- **CHANGED**: `test_widget_origin_csp.py::test_chat_rejects_token_after_origin_removed_from_allowlist`
  (T059b/SC-008) → rewrite to assert C-C3 (chat still **200** after origin
  removed) instead of 401.
- **CHANGED**: `test_chat_succeeds_when_origin_still_on_allowlist` → simplify to
  "valid token → 200" (origin allowlist no longer relevant).
- **ADD**: chat **200** with `Origin == <backend origin>` and no `Origin` at all.
- **UNCHANGED**: 401 paths for missing/garbage/wrong-key/expired tokens
  (`test_widget_session.py` chat-401 group); cross-tenant isolation test.
