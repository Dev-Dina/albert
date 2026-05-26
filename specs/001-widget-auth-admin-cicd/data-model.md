# Phase 1 Data Model — Widget Auth, Admin UX & CI/CD

All entities below are **tenant-scoped** unless explicitly marked platform-level.
Every tenant-scoped table carries a non-null `tenant_id` FK to `tenants.id` and
is covered by a PostgreSQL Row-Level Security (RLS) policy that restricts
SELECT/INSERT/UPDATE/DELETE to rows where `tenant_id = current_setting('app.tenant_id')::uuid`.

The RLS session variable `app.tenant_id` is set by `app/core/tenant_context.py`
immediately after token verification and before any tenant-scoped query runs.
A tenant context that is **not** set must cause the query to return zero rows
(achieved with `FORCE ROW LEVEL SECURITY`); never silently fall through.

## E1. Widget

A per-tenant embeddable chat instance.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK, default `uuid4` | Internal id; never exposed in HTML. |
| `tenant_id` | UUID | FK `tenants.id`, NOT NULL, ON DELETE CASCADE, indexed | Tenant scope. |
| `public_widget_id` | TEXT | NOT NULL, UNIQUE | Opaque public id used in `<script data-widget-id="…">`. 22-char base62, generated server-side. Safe to put in host HTML. |
| `name` | TEXT | NOT NULL | Admin-facing label only. |
| `theme` | JSONB | NOT NULL, server default `'{}'` | `{primary_color, font, …}`. Free-form for v1. |
| `greeting` | TEXT | NOT NULL, server default `''` | Visitor-facing first message. |
| `status` | TEXT | NOT NULL, server default `'enabled'`, CHECK in (`enabled`, `disabled`) | Disabled widgets refuse token exchange. |
| `created_at` | TIMESTAMPTZ | NOT NULL, server default `now()` | |
| `updated_at` | TIMESTAMPTZ | NOT NULL, server default `now()`, ON UPDATE `now()` | |

**Validation**:
- `public_widget_id` must match `^[A-Za-z0-9]{22}$`; never accept client-supplied values.
- `greeting` length ≤ 500 chars.

**Relationships**:
- 1 tenant → many widgets.
- Session tokens are signed by the **tenant's** signing key (see E2), not the widget's.

## E2. TenantSigningKeyVersion

Metadata for the per-tenant signing key. Actual key material lives in Vault at
`secret/data/tenant/{tenant_id}/widget_signing_key`.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tenant_id` | UUID | FK `tenants.id`, NOT NULL, ON DELETE CASCADE, indexed | Tenant scope. |
| `version` | INTEGER | NOT NULL | Monotonically increasing per tenant. Matches Vault KV v2 version. |
| `is_active` | BOOLEAN | NOT NULL, default FALSE | Exactly one row per tenant has `is_active = TRUE`. Enforced by partial unique index on `(tenant_id) WHERE is_active`. |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()` | |
| `created_by_user_id` | UUID | FK `users.id`, ON DELETE SET NULL | Audit trail for rotation actor. |
| `rotated_at` | TIMESTAMPTZ | nullable | When a newer version superseded this row. |

**State transitions** (rotation):
1. Fetch current active row for tenant; mark `is_active = FALSE`, set `rotated_at = now()`.
2. Write new key material to Vault — Vault returns the new version number.
3. INSERT new row with `version = (max(version) + 1)`, `is_active = TRUE`.
4. Both steps happen inside the same backend transaction + Vault write; on Vault
   failure, roll back the Postgres change.

**Validation**:
- Key material never appears in any logged structured field.
- Admin-side rotation endpoint returns only `{version, created_at}` — never the secret.

## E3. WidgetAllowedOrigin

Per-tenant origin allowlist. Drives CORS, `frame-ancestors`, and the server-side
origin check during token exchange.

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tenant_id` | UUID | FK `tenants.id`, NOT NULL, ON DELETE CASCADE, indexed | Tenant scope. |
| `origin` | TEXT | NOT NULL | Exact origin: scheme + host + port. |
| `created_at` | TIMESTAMPTZ | NOT NULL, default `now()` | |
| `created_by_user_id` | UUID | FK `users.id`, ON DELETE SET NULL | |

**Constraints**:
- UNIQUE on `(tenant_id, origin)`.
- `origin` must satisfy: scheme ∈ {`http`, `https`} (http only allowed when host is `localhost` or `127.0.0.1`), no path, no fragment, no query string, no trailing `/`, no `*` (wildcards explicitly rejected per FR-014).
- Normalised on write: lowercased host, default port stripped (`https://example.com:443` → `https://example.com`).

## E4. WidgetGuardrailConfig

Tenant-editable layer of guardrail settings. Bounded below by the platform floor
(see `guardrails/app/platform_floor.yaml`).

| Field | Type | Constraints | Notes |
|---|---|---|---|
| `id` | UUID | PK | |
| `tenant_id` | UUID | FK `tenants.id`, NOT NULL, ON DELETE CASCADE, UNIQUE | One config per tenant. |
| `config` | JSONB | NOT NULL, server default `'{}'` | Free-form; structure mirrors the floor file. |
| `updated_at` | TIMESTAMPTZ | NOT NULL, default `now()`, ON UPDATE `now()` | |
| `updated_by_user_id` | UUID | FK `users.id`, ON DELETE SET NULL | |

**Validation** (at admin-write time, enforced in `services/guardrail_floor.py`):
- Recursively walk `config`. For any key present in the floor, the tenant value MUST
  be at least as strict as the floor (e.g. if floor says `block_topics: ["medical_advice"]`,
  the tenant cannot remove `medical_advice` from its block list).
- Any attempt to weaken returns HTTP 422 with `{floor_value, attempted_value, key_path}`
  so the admin app can render a specific message (FR-019).

## E5. WidgetSessionToken (transient — not stored)

Issued by the token-exchange endpoint; not persisted anywhere.

JWT structure (HS256 with per-tenant signing key from E2):
```json
{
  "iss": "albert",
  "sub": "widget:<public_widget_id>",
  "tnt": "<tenant_id>",
  "wid": "<widget.id>",
  "kvr": <signing_key_version>,
  "org": "<allowed_origin_used_at_exchange>",
  "iat": <unix>,
  "exp": <iat + 900>
}
```

**Verification path** (every chat request):
1. Parse Bearer token, read `tnt`, `kvr`.
2. Fetch active key version metadata for `tnt`; reject 401 if `kvr` != active version
   (key rotated).
3. Fetch key material from Vault (60 s in-process cache).
4. Verify HS256 signature; reject 401 on mismatch.
5. Verify `exp` (±60 s skew tolerance per Edge Cases); reject 401 on expiry.
6. Set `SET LOCAL app.tenant_id = tnt` on the request's DB session; this is the
   sole source of tenant identity for the rest of the request.
7. Ignore any `tenant_id` field in the request body (FR-009).

## E6. CIGateResult (informational — not in Postgres)

Recorded as a GitHub Actions step output and as a JSON artifact under
`artifacts/ci-gate-results.json` per CI run. Not persisted in the application
database in v1; surfaced in the PR via a Markdown summary.

| Field | Type | Notes |
|---|---|---|
| `gate_name` | string | One of `lint`, `typecheck`, `image_build`, `smoke`, `classifier`, `agent_tool_selection`, `rag`, `redteam_cross_tenant`, `redaction`. |
| `status` | enum `pass`/`fail`/`error` | `error` = harness crashed; `fail` = below threshold. |
| `observed_value` | number or null | E.g. 0.62 for macro-F1. Null for binary gates if pass. |
| `threshold` | number or null | From `eval_thresholds.yaml`. |
| `details_url` | string | Link to the Actions step. |

## RLS policies summary

For each of `widgets`, `widget_allowed_origins`, `widget_guardrail_configs`,
`widget_signing_key_versions` the same shape applies (added in migration `0003`):

```sql
ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
CREATE POLICY <table>_tenant_isolation ON <table>
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
```

**Exception**: The token-exchange path needs to read a `Widget` row *before* a
tenant context exists (the public `widget_id` is the lookup key, and the result
of the lookup is what tells us the tenant). This single read uses a small
SECURITY DEFINER function `lookup_widget_by_public_id(text)` that returns only
`(widget_id, tenant_id, status)` — never any other column — and only to callers
holding the backend DB role. All subsequent reads in that request happen under
the resolved tenant context.

## Entity → spec requirement traceability

| Spec FR | Entities involved |
|---|---|
| FR-001..005 (loader/bundle) | Widget (read-only) |
| FR-006..008c (token exchange + re-exchange) | Widget, TenantSigningKeyVersion, WidgetAllowedOrigin, WidgetSessionToken |
| FR-009 (body tenant_id ignored) | WidgetSessionToken (`tnt` claim is sole source) |
| FR-010..010b (per-tenant key, rotate-only) | TenantSigningKeyVersion + Vault |
| FR-011..015 (allowlist + CORS + CSP) | WidgetAllowedOrigin |
| FR-015a..15c (rate limit) | None (Redis-only) |
| FR-016..020 (admin UX) | Widget, WidgetAllowedOrigin, WidgetGuardrailConfig, TenantSigningKeyVersion |
| FR-021..030 (CI gates) | CIGateResult (informational) |
