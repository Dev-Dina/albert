# Feature Specification: Widget Auth, Admin UX & CI/CD (Owner D)

**Feature Branch**: `001-widget-auth-admin-cicd`

**Created**: 2026-05-26

**Status**: Draft

**Input**: User description: "OWNER D — Widget Auth, Admin UX & CI/CD. Embeddable widget + /widget.js loader, signed per-widget token exchange, per-tenant origin allowlist (CSP frame-ancestors + CORS) plus server-side origin check, admin Streamlit config page (widgets, guardrail config, embed snippet), and four CI eval gates + smoke test with thresholds in eval_thresholds.yaml."

## Clarifications

### Session 2026-05-26

- Q: Should the per-tenant `allowed_origins` allowlist support subdomain wildcards in v1, or is exact-origin-only sufficient? → A: Exact origin match only (scheme + host + port); wildcards are out of scope for v1.
- Q: What is the scope of the signing key used to mint widget session tokens — per-widget, per-tenant, or one platform-wide key? → A: Per-tenant signing key, shared across that tenant's widgets; a leak or rotation is contained to one tenant.
- Q: How should the public, anonymous `/widget.js` token-exchange endpoint be rate-limited to defend against DoS and cost-abuse? → A: Per-tenant AND per-source-IP rate limit, both gates checked; conservative defaults committed in centralized config (not hard-coded).
- Q: How should the widget handle session-token expiry — silent re-exchange, separate refresh token, or visitor-facing prompt? → A: Silent re-exchange via the existing `widget_id` + origin flow (proactive before expiry, reactive on 401). No separate refresh-token primitive in v1.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Visitor chats through an embedded widget on the tenant's site (Priority: P1)

A business (tenant) pastes a one-line script tag on their public website. A visitor lands on that page, the chat widget appears with the tenant's theme and greeting, the visitor sends a message, and the assistant responds. The visitor is anonymous; the conversation is scoped to the embedding tenant by the platform — not by anything the page or the visitor sends in the request body.

**Why this priority**: This is the primary product surface the user sees. Without a working embed + authenticated chat path, the platform has no shippable demo and no way for any other owner's work (agent, RAG, guardrails) to reach a real visitor.

**Independent Test**: On a test tenant configured with an allowed origin, paste the embed snippet into a static HTML page served from that origin, open the page in a browser, send a message, and confirm a response is rendered. No other admin or CI work is required for this story to deliver value.

**Acceptance Scenarios**:

1. **Given** a tenant with `allowed_origins = ["https://demo.example.com"]` and an active widget, **When** a visitor opens `https://demo.example.com/` containing the embed snippet, **Then** the widget loads, displays the tenant's configured greeting and theme, and successfully exchanges the public `widget_id` for a short-lived session token.
2. **Given** the visitor has a valid session token, **When** they send a chat message, **Then** the request succeeds and the response is associated with the embedding tenant in stored conversation history.
3. **Given** the visitor's session token is missing, expired, or signature-invalid, **When** they send a chat message, **Then** the API rejects the request with a 401 and the widget surfaces a non-technical "session expired" state.

---

### User Story 2 - Platform refuses cross-tenant and disallowed-origin abuse (Priority: P1)

An attacker tries three abuse paths against the widget API: (a) embed the widget on a domain that is not on the tenant's allowlist; (b) call the chat endpoint directly with `curl` using a copied `widget_id` and a forged or stale token; (c) call the chat endpoint with a valid token but a request body that includes a different `tenant_id`. All three must fail, visibly, and without leaking another tenant's data.

**Why this priority**: Tenant isolation is the project's highest-priority guarantee (per CLAUDE.md). A widget that can be spoofed from a non-browser caller or that trusts a body-supplied `tenant_id` is a one-line cross-tenant breach and blocks the whole product from shipping.

**Independent Test**: Run a scripted red-team suite that performs these three attacks against a running stack and asserts each is rejected. Verifiable without any UI by inspecting HTTP responses and server logs.

**Acceptance Scenarios**:

1. **Given** a tenant whose allowlist is `["https://demo.example.com"]`, **When** the same embed snippet is loaded from `https://attacker.test/`, **Then** the visitor's browser blocks the iframe due to `Content-Security-Policy: frame-ancestors`, the `/widget.js` token-exchange call is rejected with HTTP 403 by the server-side origin check, and the rejection appears in the browser console as a real error (not a silent failure).
2. **Given** an attacker has copied a public `widget_id` and crafted or replayed a token, **When** they send a chat request with `curl` (no browser, no CORS), **Then** the API rejects the request with 401/403 based on token verification — CORS is not relied on as the gate.
3. **Given** a visitor holds a valid session token for Tenant A, **When** their chat request body also contains `"tenant_id": "<Tenant B>"`, **Then** the API ignores the body field and serves the request strictly under Tenant A's RLS context, never touching Tenant B's data.
4. **Given** a tenant rotates or revokes a widget's signing key, **When** any previously issued session token is presented after the revocation, **Then** the token is rejected.

---

### User Story 3 - Tenant admin self-serves widget + guardrail configuration and grabs the embed snippet (Priority: P2)

A tenant admin opens the admin app, views their widgets, edits theme/greeting and the per-tenant guardrail configuration, manages the origin allowlist, and copies a ready-to-paste embed snippet for their public site. The admin never has to ask an engineer for a script tag or to edit a YAML file to change a greeting.

**Why this priority**: Necessary for the demo and for any tenant to actually onboard themselves, but the embed + auth path (P1) and the safety gates (P1) can be demonstrated with seed data before this exists.

**Independent Test**: Log in to the admin app as a tenant admin, change the widget greeting and add a new allowed origin, save, then reload the embed on a page served from the new origin and observe the new greeting. No code change required between save and effect.

**Acceptance Scenarios**:

1. **Given** an authenticated tenant admin, **When** they open the Widgets page, **Then** they see only their own tenant's widgets and cannot view or address widgets belonging to any other tenant.
2. **Given** an admin updates the widget's greeting and theme and clicks save, **When** a visitor next loads the widget, **Then** the new greeting and theme are reflected without any code deploy.
3. **Given** an admin adds `https://new-site.example.com` to the origin allowlist, **When** the embed is loaded from that origin, **Then** the token exchange succeeds; conversely, removing an origin causes subsequent loads from that origin to be refused.
4. **Given** an admin opens the embed snippet panel, **When** they copy the snippet, **Then** the snippet contains their widget's public `data-widget-id` and pastes into a host page as a single script tag with no manual editing required.
5. **Given** an admin edits the tenant's guardrail configuration, **When** they attempt to weaken a platform guardrail below its non-negotiable floor, **Then** the admin app refuses the change and explains why (platform guardrails cannot be weakened by tenant config).

---

### User Story 4 - CI blocks merges that would silently degrade the agent (Priority: P2)

On every push to a branch and every pull request, the CI pipeline runs lint, type-check, builds images, brings up the stack, and runs the agent-quality and safety eval gates. If any gate regresses below the thresholds committed in `eval_thresholds.yaml`, the check fails and the PR cannot be merged. A green build means: nothing in this change made the classifier, the tool-selection agent, RAG retrieval, redaction, or the cross-tenant defenses measurably worse, and the stack still boots from a fresh clone.

**Why this priority**: The other three stories make the agent visibly good once; CI is what keeps it good across four owners merging in parallel. It is P2 only because the gates can stand up after a thin slice of the widget + auth path exists to gate against.

**Independent Test**: Open a PR that deliberately degrades one of the gated artifacts (e.g., breaks a redaction rule, weakens cross-tenant filter, removes a tool from the agent toolbelt). CI must fail on the corresponding gate with a message that identifies which gate failed and the observed vs threshold value. Reverting the change makes CI green again.

**Acceptance Scenarios**:

1. **Given** a PR with no functional changes, **When** CI runs, **Then** all six checks (lint, type-check, image build, four eval gates, smoke test) execute and pass, and the run is reproducible on a fresh clone.
2. **Given** a PR that lowers classifier macro-F1 below the threshold in `eval_thresholds.yaml`, **When** CI runs, **Then** the classifier-eval gate fails and the PR is blocked from merging.
3. **Given** a PR that introduces any change which lets a cross-tenant red-team prompt succeed, **When** CI runs, **Then** the injection/cross-tenant gate fails — every attempt in the red-team set must fail for the gate to pass.
4. **Given** a PR that disables the secret-redaction rule, **When** CI runs, **Then** the redaction test fails because the planted fake key appears in output.
5. **Given** a PR that breaks `docker-compose` startup, **When** CI runs, **Then** the smoke test fails before any eval gate runs.
6. **Given** the eval thresholds in `eval_thresholds.yaml` are tightened, **When** CI re-runs on `main`, **Then** the tightened thresholds become the new floor that future PRs must meet.

---

### Edge Cases

- **Token replay after origin change**: an admin removes an origin from the allowlist while a visitor on that origin holds an unexpired token — the next chat request from that token must be refused on origin re-check, not honored until natural expiry.
- **Clock skew on token verification**: a small skew tolerance is permitted; tokens older than the tolerated skew past expiry are rejected.
- **Widget bundle cached at an old version**: a visitor's browser may hold an older bundle in cache; the loader and bundle must be versioned so that breaking changes do not silently fail in the wild.
- **Iframe in iframe / nested embedding**: an attacker page wraps the allowed page in its own iframe to evade `frame-ancestors`. CSP must be set such that the widget refuses to render when the top-level frame ancestor is not on the allowlist.
- **Loader script tag with no `data-widget-id`**: the loader must fail closed with a clear console error, not silently inject an unauthenticated iframe.
- **Tenant with zero allowed origins**: no embed can succeed; the admin app must surface this state clearly rather than letting a widget appear broken in production.
- **CI flake**: a transient infra failure must not be silently retried into a pass; flakes must be visibly distinguishable from real regressions.
- **Token-exchange flood**: a script in a loop on an allowed origin (or a coordinated set of IPs) hits the token-exchange endpoint at high rate. Per-IP and per-tenant rate limits must each refuse with HTTP 429 once their respective threshold is crossed, and neither limit alone may be sufficient to drain the other.
- **First merge to `main` with no prior baseline**: gates must have a defined initial threshold (committed in `eval_thresholds.yaml`) so the very first run is not a free pass.
- **Two tenants share a host but different paths**: origin allowlisting is at the origin granularity (scheme + host + port); per-path scoping is out of scope for v1.

## Requirements *(mandatory)*

### Functional Requirements

**Embeddable widget & loader**

- **FR-001**: The platform MUST serve a public loader script at a stable URL (`/widget.js`) that a tenant can include with a single `<script>` tag carrying a `data-widget-id` attribute.
- **FR-002**: The loader MUST inject the chat widget into the host page in a way that isolates the widget's DOM and styles from the host page (i.e., via an iframe), so host page CSS or JavaScript cannot read or alter widget contents.
- **FR-003**: The widget MUST load its theme, greeting, and any other display-time configuration from tenant configuration at runtime — no per-tenant rebuild of the bundle.
- **FR-004**: The widget bundle and loader MUST be served with cache headers that allow long-lived caching of versioned assets while letting tenants pick up tenant-config changes (theme/greeting/allowlist) on the next widget load.
- **FR-005**: The loader MUST fail closed (no iframe injected, clear console error) if `data-widget-id` is missing, malformed, or refers to a widget that the server refuses.

**Per-widget signed token exchange**

- **FR-006**: On load, the widget MUST exchange the public `widget_id` (together with the embedding origin reported by the browser) for a short-lived, tenant-scoped session token issued and signed by the API.
- **FR-007**: Every subsequent chat or related widget API call MUST carry the session token; requests without a valid token MUST be rejected with HTTP 401.
- **FR-008**: The session token MUST be short-lived (assumed default: 15 minutes; final value set in plan) and MUST be re-obtainable by the widget without visitor friction when it expires.
- **FR-008a**: When a session token approaches expiry, the widget MUST silently re-exchange the public `widget_id` (with the same origin check) for a fresh session token using the same endpoint as the initial exchange — no separate refresh-token primitive is issued or stored in v1.
- **FR-008b**: If a chat request returns HTTP 401 due to expiry, the widget MUST attempt a single silent re-exchange and retry the failed request before surfacing any visitor-facing error; a visitor-facing "session expired" state MUST appear only when re-exchange itself is refused (e.g., origin removed, key rotated, widget disabled, or rate-limit cap hit).
- **FR-008c**: Silent re-exchange MUST itself be subject to the per-tenant and per-IP rate limits in FR-015a; a refused re-exchange MUST NOT trigger an unbounded retry loop in the widget.
- **FR-009**: The API MUST derive the request's `tenant_id` solely from the verified session token and MUST set the database tenant (RLS) context from it; any `tenant_id` field in the request body MUST be ignored.
- **FR-010**: Each tenant MUST have its own signing key used to mint and verify session tokens for all of that tenant's widgets; the platform MUST NOT use a single global key, and MUST NOT issue per-widget keys for v1. Rotating a tenant's key MUST invalidate all of that tenant's outstanding session tokens without affecting any other tenant.
- **FR-010a**: The admin app MUST expose a per-tenant "rotate signing key" action that is restricted to that tenant's admins and that produces a clear confirmation surface (because rotation will sign every currently-open visitor out of every widget for that tenant).
- **FR-010b**: Tenant signing keys MUST be stored such that they are not readable by tenant admins through the admin app or any tenant-scoped API — admins can rotate but cannot read the secret.

**Per-tenant origin allowlist (defense-in-depth)**

- **FR-011**: Each tenant MUST have an `allowed_origins` list stored in the database and editable by the tenant admin; no allowed-origin values may be hard-coded in environment variables.
- **FR-012**: The API's CORS policy and the `Content-Security-Policy: frame-ancestors` directive served with the widget MUST be derived per-widget from that tenant's `allowed_origins`.
- **FR-013**: The token-exchange endpoint MUST perform a server-side origin check against the tenant's allowlist and MUST reject with HTTP 403 when the embedding origin is not on the list — regardless of whether the caller is a browser.
- **FR-014**: Origin matching MUST be performed at origin granularity (scheme + host + port) and MUST be an exact match. Subdomain wildcards (e.g., `https://*.tenant.com`) and glob patterns are out of scope for v1 and MUST be rejected by allowlist input validation in the admin app.
- **FR-015**: CORS and CSP are explicitly treated as embedding/defense-in-depth controls and MUST NOT be the sole mechanism trusted to authenticate a caller; the signed token is the trust boundary.
- **FR-015a**: The token-exchange endpoint MUST enforce rate limits on two independent dimensions: per-source-IP and per-tenant. A request that exceeds either limit MUST be refused with HTTP 429 and an explicit `Retry-After` indication; both limits MUST be checked on every call so neither dimension alone can be exhausted.
- **FR-015b**: Rate-limit values MUST live in centralized configuration (not hard-coded in route handlers), and MUST be tunable per environment without code changes; the chosen defaults MUST be conservative enough that a single misbehaving page cannot exhaust an entire tenant's budget for normal visitors.
- **FR-015c**: Rate-limit rejections MUST be logged with enough context (tenant, dimension that tripped, count) to be triaged operationally, and MUST NOT leak any other tenant's identifiers in the response or logs.

**Admin configuration UX (Streamlit)**

- **FR-016**: A tenant admin MUST be able to view, create, and edit the widgets that belong only to their tenant; the admin app MUST never expose another tenant's widgets, configuration, or stats.
- **FR-017**: A tenant admin MUST be able to edit their widget's theme and greeting and have those changes take effect on the next widget load with no code deploy.
- **FR-018**: A tenant admin MUST be able to view, add, and remove entries in their `allowed_origins` list, and changes MUST take effect for subsequent token exchanges.
- **FR-019**: A tenant admin MUST be able to view and adjust their tenant-level guardrail configuration; the admin app MUST refuse any change that would weaken a platform-level guardrail below its non-negotiable floor.
- **FR-020**: The admin app MUST present a copy-ready embed snippet containing the tenant's public `data-widget-id` and the loader URL, with no manual editing required to paste it into a host page.

**CI/CD pipeline & quality gates**

- **FR-021**: A CI pipeline (GitHub Actions) MUST run on every push and pull request and MUST execute, in order: lint, type-check, image build, stack smoke test, and the eval/safety gates.
- **FR-022**: Threshold values for every gated metric MUST be committed in a single source-controlled file `eval_thresholds.yaml`; raising or lowering a threshold MUST be a reviewable change.
- **FR-023**: The pipeline MUST include a **classifier eval** gate that measures macro-F1 on the held-out test set and fails the build if the observed value falls below the committed threshold.
- **FR-024**: The pipeline MUST include an **agent tool-selection** gate against a golden set that fails the build if the agent picks a wrong tool above the committed error budget.
- **FR-025**: The pipeline MUST include a **RAG golden-set** gate measuring retrieval and generation metrics and fail the build if those fall below committed thresholds.
- **FR-026**: The pipeline MUST include an **injection / cross-tenant red-team** gate; the gate MUST fail unless every attack attempt in the set is refused — i.e., the bar is 100%, not a percentage, and is non-negotiable.
- **FR-027**: The pipeline MUST include a **redaction** gate that asserts a planted fake secret never appears in agent output, logs, or stored traces; any leak fails the build.
- **FR-028**: The pipeline MUST include a **stack smoke test** that brings the full `docker-compose` stack up from a fresh clone and verifies basic endpoint health; failure here MUST short-circuit before the eval gates run.
- **FR-029**: Gate failures MUST report which gate failed and the observed vs. threshold value so a contributor can act without digging through raw logs.
- **FR-030**: CI MUST NOT silently retry failing gates; flakes MUST be distinguishable from real regressions.

### Key Entities *(include if feature involves data)*

- **Widget**: A per-tenant embeddable chat instance. Carries a public `widget_id` (safe to expose in host HTML), a theme + greeting, a status (enabled/disabled), and a reference to its owning tenant. Belongs strictly to one tenant. Session tokens for a widget are signed with that tenant's signing key (see **Tenant Signing Key**), not a key owned by the widget itself.
- **Tenant Signing Key**: A per-tenant secret used to mint and verify all widget session tokens for that tenant. Stored such that no tenant admin can read it; admins can only trigger rotation. Rotation invalidates every outstanding session token for that tenant in a single action.
- **Allowed Origin**: An entry on a tenant's allowlist (scheme + host + port). Drives both the CORS policy and the `frame-ancestors` directive emitted for that tenant's widget, and is checked server-side during token exchange.
- **Widget Session Token**: A short-lived, tenant-scoped credential issued by the token-exchange endpoint to a widget instance after origin verification. Carries the tenant identity used to set the request's RLS context. Verifiable by the API on every subsequent call.
- **Embed Snippet**: The copy-ready `<script>` tag presented to admins, containing the loader URL and the tenant's `data-widget-id`. Not stored per se — derived from the widget record.
- **Tenant Guardrail Configuration**: The tenant-editable layer of guardrail settings (e.g., topic allowlist, tone). Bounded below by a non-negotiable platform floor that tenant edits cannot pierce.
- **Eval Thresholds File (`eval_thresholds.yaml`)**: A single source-controlled file that holds the minimum acceptable values for each CI gate (classifier macro-F1, tool-selection accuracy, RAG retrieval/generation metrics, redaction pass-rate, cross-tenant attempt-failure rate = 100%).
- **CI Gate Result**: The recorded outcome (pass/fail, observed value, threshold, gate name) of one gate run on one commit. Used to surface why a build failed.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A tenant admin can take an empty widget configuration to a working embed on their public site (set theme, set greeting, add an allowed origin, copy snippet, paste into host page, see widget chat respond) in under 10 minutes, end-to-end, with no engineer assistance.
- **SC-002**: 100% of cross-tenant red-team attempts in the committed test set are rejected on every CI run; a single success is a hard build failure, not a percentage degradation.
- **SC-003**: A widget loaded from a disallowed origin is blocked in three independent ways on every check: the browser shows a real CSP/frame-ancestors error in the console, the token-exchange call returns HTTP 403, and a direct (non-browser) call with a copied `widget_id` from that origin is also rejected.
- **SC-004**: A request that includes a forged or stale session token is rejected with HTTP 401 in 100% of test cases, including when CORS would otherwise have permitted the caller's origin.
- **SC-005**: A planted fake secret never appears in any agent response, log line, or stored trace under the redaction test set — leak rate is 0.
- **SC-006**: Every push to a branch triggers a CI run whose pass/fail outcome on each of the six checks (lint, type-check, image build, four+ eval gates, smoke test) is visible on the PR within the team's agreed CI time budget, and a fresh clone reproduces the run.
- **SC-007**: When an admin changes a widget's greeting or theme, the change is reflected to the next visitor's widget load with no code deploy and within one bundle cache cycle.
- **SC-008**: When an admin removes an origin from the allowlist, no new session tokens can be minted for that origin and existing tokens stop being honored on the next request from that origin.
- **SC-009**: At least one demonstrable scenario per high-priority story (US1 visitor chat on allowed host, US2 disallowed host + curl + body-`tenant_id` attacks all rejected) can be shown live in the Friday demo without ad-hoc code changes.

## Assumptions

- The widget's first delivered surface is **chat**; richer features (lead capture forms, scheduling, file uploads) are out of scope for v1 of this feature.
- A widget visitor is **anonymous** — there is no logged-in end user; the only identity the API needs from a widget call is the **tenant**, derived from the verified session token.
- The admin app is the **Streamlit** surface called out in the project (not a separate SPA); per-tenant admin auth is provided by the auth work owned elsewhere on the team and is consumed here.
- Origin matching is **exact** (scheme + host + port) for v1; subdomain wildcards and glob patterns are explicitly out of scope (see Clarifications).
- Token validity defaults to **~15 minutes** with silent re-exchange by the widget via the existing token-exchange flow (no separate refresh token); final value is set in the plan and committed in centralized config, not hard-coded.
- The widget bundle is small enough to serve directly from the API service (or MinIO) without a separate CDN in v1; a future CDN can sit in front without changing the loader URL contract.
- `eval_thresholds.yaml` lives at the repository root (or under a `ci/` directory) so that any owner can see and review threshold changes in PRs.
- The four eval data sets (classifier test set, tool-selection golden set, RAG golden set, cross-tenant red-team set) are produced by the owners of those features (A/B/C); this feature owns the **gate plumbing**, the thresholds file, and the smoke test — not the data sets themselves.
- The redaction rule under test is the existing platform redaction layer; this feature's responsibility is to gate on it, not to (re)implement it.
- Pre-existing tenant + RLS infrastructure (tenants table, RLS session context helper, auth) from earlier phases is available to this feature; this feature consumes it and MUST NOT bypass it.
