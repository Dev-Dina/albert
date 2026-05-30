# Phase 1 Data Model: Widget Cross-Origin Session & Chat Fix

**No schema changes.** This feature changes request-handling behavior only. The
entities below already exist; they are documented to show what each one's
enforcement role becomes under Approach A.

## Entities (existing, unchanged shape)

### Widget
- **Identity**: public `widget_id` (22-char base62), resolved server-side to
  exactly one `tenant_id` via a SECURITY DEFINER lookup.
- **Attributes**: `status` (`enabled`/disabled), theme, greeting.
- **Role in this feature**: source of server-derived tenant identity at session
  exchange. Unchanged.

### Widget Allowed Origin (`widget_allowed_origins`)
- **Identity**: (`tenant_id`, `origin`) — tenant-scoped under FORCE RLS.
- **Attributes**: `origin` (customer site origin), `created_by_user_id`.
- **Role change**: previously consulted at **three** points — `frame-ancestors`
  (embed page), `/session` exchange, and `/chat` re-check. **After this feature**
  it is consulted at **one** point: building the `frame-ancestors` CSP for
  `embed.html` (the embedding control). The `/session` and `/chat` consultations
  are removed.
- **Lifecycle**: admin add/remove via the existing admin UI/API. Adding enables
  embedding from that origin; removing immediately blocks new embeds. No
  migration; admin management unchanged.

### Widget Signing Key Version (`widget_signing_key_versions`)
- **Identity**: (`tenant_id`, `version`), with one `is_active` row per tenant.
- **Role**: pins the token's `kvr` claim; key material lives in Vault. Unchanged.

### Widget Session Token (signed, not persisted)
- **Claims**: `iss`, `sub` (`widget:<public_id>`), `tnt` (tenant), `wid`
  (widget), `kvr` (key version), `org` (origin captured at exchange), `iat`,
  `exp`.
- **Role change**: the `org` claim becomes **informational only** — it is no
  longer re-validated against the allowlist on `/chat`. Tenant authorization
  rests on signature + `kvr` + `tnt`. TTL (`exp - iat`, currently 900 s) is the
  exposure bound after an allowlist change (FR-017).
- **Lifecycle**: minted by `/session`, verified per `/chat` request, expires by
  TTL. The widget bundle re-exchanges on a 401 (unchanged client behavior).

## Validation rules affected

| Rule | Before | After (Approach A) |
|------|--------|--------------------|
| `/session`: request `Origin` present | Required (400 if missing) | **Required (unchanged, FR-009)** |
| `/session`: `Origin` well-formed | Required (else uniform 403) | **Required (unchanged, hygiene)** |
| `/session`: `Origin` ∈ customer allowlist | Required (else uniform 403) | **Removed** |
| `/chat`: bearer token valid signature + active `kvr` | Required (else 401) | **Required (unchanged)** |
| `/chat`: request `Origin` present | Required (else 401) | **Removed** |
| `/chat`: request `Origin` ∈ customer allowlist | Required (else 401) | **Removed** |
| `embed.html`: `frame-ancestors` = tenant allowlist | Enforced | **Enforced (unchanged — sole allowlist consumer)** |

## State / data transitions

- **Admin removes an allowed origin** → next `embed.html` render for that tenant
  omits the origin from `frame-ancestors` (new framing blocked immediately);
  already-issued tokens continue to authorize `/chat` until they expire.
- **Admin empties the allowlist** → `embed.html` returns 404 (not framable
  anywhere); `/session` still mints tokens to direct callers, but no browser can
  frame the widget.
