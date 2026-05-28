# Phase 0 Research — Widget Auth, Admin UX & CI/CD

All NEEDS CLARIFICATION items from spec.md were resolved either in the 2026-05-26
clarification session or in the research below.

## R1. Session-token TTL

**Decision**: 15 minutes; silent re-exchange (proactive at T-2 min, reactive on 401).

**Rationale**:
- Short enough that a stolen token is useless soon; long enough that a single visitor
  conversation typically completes in one TTL window.
- Re-exchange uses the same `widget_id` + origin path, so there is no separate
  refresh-token primitive to store, leak, or revoke (per clarification).
- 15 min aligns with widely deployed defaults (Auth0, Cognito) for ephemeral session
  tokens that pair with a longer-lived primary credential — here, the primary
  credential is the public `widget_id` + verified origin.

**Alternatives considered**:
- 5 min: too aggressive — every visitor would re-exchange mid-conversation, adding
  load to the rate-limiter and the Vault key fetch.
- 60 min: violates the "short-lived" intent and lengthens the post-rotation window
  before all outstanding tokens drop.
- Separate refresh token: rejected in the clarification session.

## R2. Rate-limit algorithm and storage

**Decision**: Token bucket per dimension (per-IP, per-tenant), stored in Redis with
an atomic Lua script. Two independent buckets; a request that exhausts either is
refused with HTTP 429 + `Retry-After`.

**Rationale**:
- Bursty traffic (one page load = 1 exchange, then re-exchange every ~13 min) fits
  token-bucket better than a fixed window.
- Redis already runs in the local stack; no new infra needed.
- A 25-line Lua script ensures atomic check-and-decrement; without atomicity the
  two-gate check can race.
- Both gates checked on every call: a single misbehaving page on one tenant cannot
  drain the per-tenant budget for honest visitors, and a botnet across IPs cannot
  bypass the per-tenant cap.

**Alternatives considered**:
- `slowapi` (FastAPI middleware): one gate per route, not two-dimensional; would
  require subclassing.
- In-process counter: would lose state on restart and cannot share across multiple
  backend replicas.
- Sliding-window log: more accurate but more Redis memory; token-bucket is
  sufficient for v1 traffic.

## R3. Widget bundle build tooling

**Decision**: **React 18 + TypeScript**, compiled with `esbuild` into a single
ESM module (`bundle-<sha>.js`) plus a tiny vanilla `widget.js` loader (no
framework in the loader itself). Output target: loader ≤ 4 KB minified;
bundle ≤ 110 KB minified, ≤ 45 KB gzipped.

**Rationale**:
- React is mandated by Owner D's scope sheet ("The React widget"). Picking it
  here aligns with team staffing and the cross-owner brief.
- `esbuild` keeps the build trivial — one binary, no Babel toolchain, no
  Vite-style config sprawl. JSX is handled natively.
- The runtime cost of React+ReactDOM (~40 KB minified, ~14 KB gzipped) is
  acceptable for a chat surface that loads inside an iframe (post first paint
  of the host page), and it pays back in maintainability if the surface grows
  beyond v1 chat.
- Bundle budget enforced in CI: a step fails the build if `widget/dist/bundle-*.js`
  exceeds the byte budget. Caught early before regressions snowball.

**Alternatives considered**:
- Vanilla TS + esbuild (no framework): smaller bundle (~30 KB), but diverges
  from the owner brief and forces hand-rolled state management for the chat UI.
- Preact: ~10 KB runtime, React-compatible API. Reasonable compromise but still
  not what the owner brief specifies.
- Vite: more configuration, slower CI build, no payoff for this single-entry
  surface; esbuild covers everything Vite would here.
- Server-side render the iframe HTML: harder to ship updates and harder to
  version-cache.

## R4. CSP `frame-ancestors` vs other embedding controls

**Decision**: Emit `Content-Security-Policy: frame-ancestors <allowlist>` on every
response that serves the widget iframe HTML. CORS is set on the JSON API endpoints
only. Server-side origin verification is the gate that authenticates the caller;
CSP and CORS are defense-in-depth.

**Rationale**:
- `frame-ancestors` is the only header that survives iframe-in-iframe wrapping
  (an attacker page that frames the allowed page). The browser walks the
  ancestor chain and rejects if any ancestor is off the list.
- `X-Frame-Options` is superseded by `frame-ancestors`; we set both for legacy
  but treat `frame-ancestors` as authoritative.
- CORS cannot stop a non-browser caller (curl), so it must never be the trust
  boundary (FR-015).

**Alternatives considered**:
- Trust CORS for auth: rejected per FR-015 — direct `curl` bypasses CORS entirely.
- Single static CSP: would have to be the union of all tenants' allowlists, which
  leaks origins across tenants. Per-tenant dynamic CSP keeps it scoped.

## R5. Per-tenant signing key — storage and rotation

**Decision**: Store key material in Vault at `secret/data/tenant/{tenant_id}/widget_signing_key`
with versions (Vault KV v2 supports versioning natively). Store key *metadata*
(active version number, created_at, created_by) in Postgres in
`widget_signing_key_versions`. Verification fetches the active version's material
from Vault, with a short in-memory cache (TTL = 60 s) to keep verify-path fast.

**Rationale**:
- Vault enforces the "admin cannot read" requirement (FR-010b): admin app and
  tenant-scoped API never have a token with read permission on this path;
  rotation calls a backend service that holds a separate, narrowly-scoped Vault
  token.
- KV v2 versioning gives us free rotation history and the ability to invalidate
  all previous versions atomically by writing a new version and bumping the
  active version number in Postgres.
- 60-second cache keeps verify-path under 5 ms p95 while ensuring rotation
  propagates within the same window (acceptable per FR-010a: rotation is
  explicitly described as a "sign every visitor out" action).

**Alternatives considered**:
- Key in Postgres `bytea`: violates FR-010b — any tenant-admin SELECT path is a
  one-line leak.
- Per-widget key: rejected in the clarification session.
- Single platform key: rejected in the clarification session.

## R6. Eval gate fixture strategy

**Decision**: Ship placeholder fixtures under `evals/*/fixtures/` with clearly
marked TODOs and `eval_thresholds.yaml` values that the placeholders pass at the
current "loose starting point" thresholds. Wire all four gates into CI so the
plumbing is exercised on every PR even before the real datasets land. When a
real dataset replaces a placeholder, the *same* PR must raise the corresponding
threshold; reviewers enforce this.

**Rationale**:
- Avoids the dead-code anti-pattern where gates exist but aren't enforced.
- Avoids the worse anti-pattern where gates are gated behind a feature flag and
  silently skipped.
- The cross-tenant red-team gate (FR-026) is the only one whose bar is **100%**
  on day 1 — that bar applies to a small initial attack set (3 attempts) and
  grows as Owner A/B/C add cases.

**Alternatives considered**:
- Skip gates until real data lands: violates FR-021 and SC-006 (CI must run all
  six checks on every PR from day 1).
- Ship gates as advisory (warn-only): a soft gate is no gate. Spec is explicit
  that a regression must **fail** the build.

## R7. Streamlit admin auth

**Decision**: Streamlit pages call the existing `POST /api/v1/auth/login`,
receive a Bearer token, and store it only in `st.session_state` (process memory,
per-user). Every backend call from Streamlit sends `Authorization: Bearer …`.
No cookie, no persisted session.

**Rationale**:
- Re-uses existing auth path (already shipped in `backend/app/api/routes/auth.py`).
- Token never touches disk on the admin host.
- Per-user `st.session_state` is the Streamlit-native primitive; no need to
  bolt on flask-session or similar.

**Alternatives considered**:
- OAuth code flow into Streamlit: overkill for v1; tenant-admin auth is the
  same JWT used by the rest of the platform.
- Shared service account for the admin app: would break tenant scoping —
  rejected.

## R8. Admin guardrail floor location

**Decision**: A single YAML at `guardrails/app/platform_floor.yaml` (NEW),
shipped with the guardrails service so the floor lives with the guardrail
implementation. Loaded by `backend/app/services/guardrail_floor.py` at startup;
admin app refuses any tenant-level edit that would weaken a key below its
floor and shows the floor value in the refusal message.

**Rationale**:
- Co-locates floor with the guardrail logic it protects.
- Backend reads the same file the guardrails service reads, so the floor cannot
  diverge between enforcement and admin-side validation.
- Owned by this feature for v1 unless Owner C (Modelserver / Guardrails) claims
  it — non-blocking either way.

**Alternatives considered**:
- Floor in `backend/app/core/config.py`: would split policy from implementation
  and require a backend deploy for every floor change.
- Floor in the database: would let an attacker with DB write target the floor
  itself.

## R9. Widget bundle versioning and caching

**Decision**: Serve `widget.js` (loader) with `Cache-Control: max-age=60`, no
hash in the URL — loader is small and may need a quick fix push. Serve the
heavier `bundle-<sha>.js` (iframe contents) with `Cache-Control: public, max-age=31536000, immutable`,
and embed the current sha in the iframe HTML at request time, so a visitor's
browser may cache the bundle for a year while still seeing breaking changes via
a fresh iframe HTML reference (which is tenant-config-driven and short-cached).

**Rationale**:
- Loader stays correctable; bundles get aggressive immutable caching keyed by
  content hash.
- Tenant-config changes (theme, greeting, allowlist) are reflected on next
  iframe load because the iframe HTML is generated per-request from the
  current widget row.

**Alternatives considered**:
- Bust cache by query string: works but is widely flagged by intermediaries as
  not-truly-immutable.
- Long-cache the loader: a fix push would require waiting for browsers to
  expire the cache — unacceptable for a public surface.

## R10. CI runtime budget

**Decision**: Target ≤ 10 minutes total CI wall clock for a PR with no cached
layers; ≤ 6 minutes with the GitHub Actions cache warm. Parallelize: lint +
type-check + image build in three concurrent jobs; smoke test depends on image
build; eval gates depend on smoke; the four eval gates run in parallel.

**Rationale**:
- Spec (FR-021) demands the gates run in order semantically but does not
  forbid topological parallelism within that order.
- Smoke-before-evals satisfies FR-028 (smoke MUST short-circuit before eval
  gates run).
- Four parallel eval jobs use four runners but each runs ≤ 90 s on
  placeholder fixtures.

**Alternatives considered**:
- Strictly sequential pipeline: simpler but blows the 10-min budget once real
  datasets land.
- One mega-job: harder to read which gate failed; violates FR-029 (must report
  which gate failed).
