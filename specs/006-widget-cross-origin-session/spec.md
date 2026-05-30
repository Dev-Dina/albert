# Feature Specification: Widget Cross-Origin Session & Chat Fix

**Feature Branch**: `006-widget-cross-origin-session`

**Created**: 2026-05-30

**Status**: Draft

**Input**: User description: "Fix the widget cross-origin session/chat bug so real third-party embeds work without weakening tenant isolation."

## Overview

A business (tenant) embeds Albert's chat widget on its own public website by
adding a small loader script. The loader injects an iframe whose document and
API both live on the Albert backend origin. When a real visitor on the
tenant's site (e.g. `https://customer.com`) opens the widget, the browser
attaches the **backend** origin to the widget's session and chat requests —
because those requests originate from inside the backend-served iframe.

The backend, however, gates the session-token exchange and the chat endpoint
by comparing that origin against the tenant's allowed-origins list, which
stores **customer site** origins. The two never match, so every genuine
third-party embed is refused (token exchange fails; chat is unauthorized).
The widget only works today on pages served from the backend's own origin
(e.g. local demos), and the automated tests pass only because they synthesize
a request carrying the customer origin — a condition the real browser flow
never produces.

This feature makes genuine cross-origin embeds work end-to-end while keeping
the platform's hard tenant-isolation guarantees intact: one tenant can never
act as another, and a widget can only be embedded and used from sites the
tenant has explicitly allowed.

## Clarifications

### Session 2026-05-30

- Q: Which architecture resolves the cross-origin session/chat bug — decouple
  the allowlist from request-time origin checks (A), or parent-origin exchange
  with CORS + postMessage handoff (B)? → A: **Approach A.** The allowlist
  governs *embedding only* (enforced by the `frame-ancestors` control using
  customer origins). Tenant identity comes solely from the signed session
  token. The `/session` and `/chat` endpoints stop comparing the request origin
  against the customer allowlist. Rationale: cross-tenant isolation is
  guaranteed by the server-derived token regardless of origin; a per-request
  origin check on a backend-served iframe is fundamentally unreliable (the root
  cause of the bug); and Approach A is the smaller, more robust change.
- Q: Under Approach A, how should already-issued tokens behave when an admin
  removes an allowed origin (the per-request origin re-check that powered
  mid-session revocation is gone)? → A: **TTL-bounded revocation.** Removing an
  origin immediately blocks *new* embeds via the `frame-ancestors` control;
  already-issued tokens stay valid only until they expire (session TTL,
  currently 900 seconds / 15 minutes). Binding the customer origin into the
  token was rejected because it would depend on an untrusted client-supplied
  origin hint that an attacker could spoof, buying no real security.
- Q: Approach A makes the chat API publicly callable by anyone holding the
  public `widget_id` (browser embedding still blocked by `frame-ancestors`).
  Is that acceptable, or is an extra request-time control needed? → A:
  **Accept it as a public, rate-limited surface.** A concierge widget is
  inherently public (visitors chat with no credentials) and `widget_id` is not
  a secret. Protection rests on three controls that remain intact: the framing
  control blocks browser embedding on non-allowlisted sites, the server-derived
  token prevents cross-tenant action, and per-IP + per-tenant rate limits bound
  abuse. Preventing non-browser API calls is explicitly NOT a goal of this fix.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Visitor on an allowlisted customer site can chat (Priority: P1)

A visitor browses a tenant's public website on a domain the tenant has added
to its allowed origins. They open the embedded Albert widget, send a message,
and receive a reply. The whole round trip succeeds without manual steps or
errors.

**Why this priority**: This is the core defect. Without it, the widget does
not function for any real customer — the product's central promise (embed an
AI agent on your site) is broken in production conditions.

**Independent Test**: Serve a host page from a domain that is on the tenant's
allowlist but is NOT the backend origin, load the widget, and confirm a
message sent through the widget returns a reply. This reproduces the real
browser request flow (the browser sets the origin, not the test harness).

**Acceptance Scenarios**:

1. **Given** a tenant whose allowlist contains `https://customer.com` and a
   host page served from `https://customer.com`, **When** a visitor opens the
   widget, **Then** a session is established successfully (no refusal).
2. **Given** an established widget session on `https://customer.com`, **When**
   the visitor sends a chat message, **Then** the system returns a reply
   scoped to the correct tenant.
3. **Given** the visitor continues chatting within the session lifetime,
   **When** they send further messages, **Then** each succeeds without a
   re-authentication failure.

---

### User Story 2 - Embedding from a non-allowlisted site is refused, isolation holds (Priority: P1)

A page on a domain NOT in the tenant's allowlist cannot *frame* the widget. The
chat API itself is a public, rate-limited surface (any visitor can chat), so
preventing scripted API calls is not a goal; instead the platform guarantees
that no caller — from any origin — can act as a different tenant or exceed the
abuse limits.

**Why this priority**: Tenant isolation and abuse prevention are the platform's
highest priority. The fix for User Story 1 must not become a hole that lets any
site *embed* a tenant's widget, lets a caller act as another tenant, or removes
the abuse ceiling. This invariant is co-equal with the core fix and must be
verified at the same time.

**Independent Test**: Attempt to frame the widget from an origin absent from the
allowlist and confirm the browser blocks the embed. Confirm a token issued for
one tenant can never produce a reply attributed to another. Confirm refusals
for unknown/disabled widgets reveal nothing about which tenants or widgets
exist, and that rate limits return throttling refusals.

**Acceptance Scenarios**:

1. **Given** a tenant whose allowlist does NOT contain `https://evil.example`,
   **When** a page on `https://evil.example` tries to frame the widget,
   **Then** the browser refuses to render the iframe.
2. **Given** a session token issued for Tenant A, **When** it is used to call
   chat, **Then** every reply and side effect is scoped to Tenant A and never
   to any other tenant, regardless of the calling origin.
3. **Given** a caller exceeding the per-IP or per-tenant limits, **When** it
   keeps calling, **Then** it receives a uniform throttling refusal with no
   disclosure of which limit tripped.
4. **Given** a session-exchange attempt for an unknown or disabled widget,
   **When** it fails, **Then** the response is a uniform refusal that does not
   disclose whether the widget, the tenant, or a key was the cause.
5. **Given** any refused chat attempt (invalid/expired token), **When** it
   fails, **Then** the response is a uniform unauthorized refusal that does not
   disclose the cause.

---

### User Story 3 - Admin allowlist changes take effect promptly (Priority: P2)

A tenant admin adds or removes an allowed origin. Adding an origin lets the
widget work on that site; removing an origin immediately stops the widget from
being embedded there for any new visitor, and already-issued sessions tied to
that site expire on their own within the session lifetime.

**Why this priority**: The allowlist remains the tenant-facing control over
*where* the widget may live. Its management semantics must survive the fix:
embedding control is enforced immediately, and exposure of already-issued
tokens is bounded by the session lifetime.

**Independent Test**: Remove an origin from a tenant's allowlist, then load a
page on that origin and confirm the widget can no longer be framed. Add an
origin and confirm a fresh embed from it succeeds.

**Acceptance Scenarios**:

1. **Given** the admin removes `https://customer.com` from the allowlist,
   **When** a visitor next loads a page on `https://customer.com`, **Then** the
   browser refuses to frame the widget (new embeds blocked immediately);
   already-issued sessions remain usable only until they expire (≤ session TTL).
2. **Given** a newly added allowed origin, **When** a visitor opens the widget
   from that origin, **Then** the session establishes successfully.
3. **Given** a tenant with no allowed origins, **When** anyone attempts to
   embed or use the widget, **Then** all attempts are refused.

---

### User Story 4 - Remove the temporary local-demo allowlist hack (Priority: P3)

During earlier local debugging, the backend origin (`http://localhost:8000`)
was manually added to a demo tenant's allowed origins so the local demo could
mint a session under the broken flow. Once the cross-origin flow is fixed,
that entry is no longer required and must be removed; the local demo must
continue to work through the corrected flow.

**Why this priority**: It is cleanup that confirms the fix is real — if the
demo still works after removing the workaround, the genuine cross-origin path
is functioning. Low priority because it does not affect production tenants.

**Independent Test**: Remove the backend origin from the demo tenant's
allowlist, run the local demo, and confirm the widget still establishes a
session and chats.

**Acceptance Scenarios**:

1. **Given** the temporary backend-origin allowlist entry is removed, **When**
   the local demo is run, **Then** the widget still works end-to-end.
2. **Given** the corrected flow, **When** the local demo host page is served
   from its intended demo origin, **Then** no manual allowlist workaround is
   needed for it to function.

---

### Edge Cases

- **Missing origin information**: A request that arrives without the browser
  attaching origin information is refused (the exchange requires it today and
  must continue to fail closed).
- **Malformed origin**: A request carrying a non-conforming origin value is
  refused uniformly, with no enumeration leak.
- **Disabled or unknown widget**: A session-exchange request for a disabled or
  non-existent widget is refused with a single uniform response (shared with the
  missing-signing-key case), so callers cannot distinguish the cause.
- **Origin removed mid-session**: New embeds from the removed origin are blocked
  immediately (the framing control fails); an already-issued session continues
  until its token expires (bounded by the session TTL).
- **Tenant with empty allowlist**: The widget cannot be framed anywhere (the
  embed page is refused); there is no implicit default origin.
- **Two tenants on the same customer domain**: A token minted for Tenant A must
  never authorize chat as Tenant B, even if both tenants allowlist the same
  customer origin.
- **Stale/expired session**: An expired session leads to a clean re-establish
  attempt rather than a confusing hard error for the visitor.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A visitor on a page served from an origin that is present in the
  tenant's allowed-origins list MUST be able to obtain a widget session and
  exchange chat messages successfully, under the real browser request flow
  (i.e. where the browser — not a test harness — determines the origin
  attached to widget requests).
- **FR-002**: The system MUST continue to derive tenant identity solely from
  server-trusted information (the widget identifier resolved server-side and
  the verified session token). It MUST NOT trust any tenant identifier supplied
  in a client request body.
- **FR-003**: The system MUST prevent a session or token issued for one tenant
  from being used to act as any other tenant, including when multiple tenants
  allowlist the same customer origin.
- **FR-004**: The tenant's allowed-origins list MUST remain the control that
  governs *where* the widget may be embedded: a site whose origin is not on the
  list MUST be prevented by the browser from framing the widget.
- **FR-005**: The allowed-origins list MUST remain manageable by the tenant
  admin, and changes MUST take effect for new embeds without redeploying.
- **FR-006**: Removing an origin from the allowlist MUST immediately prevent new
  embeds from that origin (the framing control MUST fail for fresh loads).
  Already-issued sessions MAY remain usable until their token expires; exposure
  is therefore bounded by the session lifetime (FR-017).
- **FR-007**: A failed session-exchange attempt (unknown widget, disabled
  widget, or missing signing key) MUST return a single uniform refusal that does
  not reveal which cause applied (anti-enumeration preserved).
- **FR-008**: A failed chat authorization MUST return a single uniform
  unauthorized refusal that does not reveal the cause.
- **FR-009**: A session-exchange request that arrives without origin
  information MUST be refused (fail closed).
- **FR-010**: Platform guardrails and isolation controls MUST NOT be weakened
  by any tenant's allowlist configuration; tenant configuration can only
  restrict, never broaden, the platform floor.
- **FR-011**: The system MUST NOT log secrets, tokens, signing keys, or raw
  sensitive values as part of the origin-handling or session flow.
- **FR-012**: The automated tests for the session and chat flows MUST exercise
  the origin condition the real browser actually produces, so that a passing
  test suite reflects a working production embed (the current tests, which
  synthesize the customer origin, MUST be corrected or augmented).
- **FR-013**: The temporary local-demo workaround that added the backend origin
  to a demo tenant's allowlist MUST be removed once the corrected flow lands,
  and the local demo MUST continue to function without it.
- **FR-014**: The rate-limiting protections on the session endpoint
  (per-source and per-tenant) MUST remain in force after the fix.

#### Chosen approach (decided in Clarifications)

**Approach A — decouple the allowlist from the request-time origin check.**
Widget requests are treated as same-origin to the backend (which they are).
Tenant identity comes from the signed per-tenant session token, and the
per-tenant frame-embedding control enforces *where* the widget may live. The
`/session` and `/chat` endpoints no longer compare the request origin against
the customer allowlist. Consequences are captured in FR-015 through FR-017
below.

- **FR-015**: The `/session` and `/chat` endpoints MUST NOT compare the request
  origin against the tenant's customer allowed-origins list. The customer
  allowlist's enforcement role is limited to the frame-embedding control
  (`frame-ancestors`) that decides where the widget may be framed.
- **FR-016**: The frame-embedding control MUST remain the authoritative,
  immediate enforcement point for *where* a widget may be embedded, and MUST
  continue to use the tenant's customer origins. A tenant with an empty
  allowlist MUST NOT be embeddable anywhere.
- **FR-017**: Exposure of an already-issued session after an allowlist change
  MUST be bounded by the session token lifetime. The session lifetime is a
  configurable platform setting (currently 900 seconds) and MUST remain short
  enough to bound this exposure.

### Key Entities *(include if feature involves data)*

- **Widget**: A tenant-owned embeddable chat surface, identified by a public
  widget identifier; resolves server-side to exactly one tenant; has an
  enabled/disabled status.
- **Allowed origin**: A tenant-scoped record naming a site origin where the
  tenant's widget may be embedded. Under Approach A it governs embedding only
  (the `frame-ancestors` framing control); it is NOT consulted by the
  request-time `/session` or `/chat` origin handling (FR-015).
- **Widget session token**: A signed, time-limited credential that carries the
  server-derived tenant and widget identity used to authorize chat. Never
  derived from client-supplied tenant data.
- **Customer (host) origin**: The origin of the tenant's public website where
  the loader runs and the iframe is embedded.
- **Backend origin**: The Albert origin that serves the loader script, the
  iframe document, and the widget API endpoints.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A host page served from an allowlisted customer origin (distinct
  from the backend origin) can complete a full chat round trip (open widget →
  send message → receive reply) with zero manual intervention.
- **SC-002**: A page on a non-allowlisted origin is prevented by the browser
  from framing the widget — verified for at least one representative disallowed
  origin. (Scripted API access from arbitrary origins is out of scope by
  design; see FR-015 and the Clarifications.)
- **SC-003**: 100% of existing tenant-isolation and widget-auth behaviors that
  currently pass continue to pass, EXCEPT the per-request origin checks that
  Approach A intentionally removes. Tests asserting the old request-time origin
  behavior (e.g. mid-session revocation via the `/chat` Origin re-check) MUST be
  updated to assert the new behavior: immediate embedding block via the framing
  control plus TTL-bounded token expiry. Uniform-refusal (no-enumeration)
  responses MUST continue to pass unchanged.
- **SC-004**: The session and chat test suites assert behavior under the origin
  value the real browser sends for a backend-served iframe, not a hand-set
  customer origin; reviewers can confirm the tests would fail if the production
  flow regressed.
- **SC-005**: After the temporary backend-origin allowlist entry is removed,
  the local demo still establishes a session and chats successfully.
- **SC-006**: No tenant can, through any allowlist configuration or request
  shape, obtain a session or chat reply attributed to a different tenant.

## Assumptions

- The widget loader will continue to serve the iframe document and the widget
  API from the Albert backend origin; relocating those to per-tenant
  subdomains is out of scope for this fix.
- The existing per-tenant frame-embedding control (the control that already
  uses customer origins to decide where the widget may be framed) is, under the
  decided Approach A, the *sole* consumer of the allowlist and the authoritative
  mechanism that enforces *where* the widget can live.
- The existing signed per-tenant session token remains the authoritative
  carrier of tenant identity for chat.
- The allowed-origins data model and admin management UI already exist and are
  reused; this feature does not redesign them.
- "Origin not allowlisted" includes the empty-allowlist case (no implicit
  default origin is granted): such a tenant cannot be framed anywhere.
- Approach A is the decided design (see Clarifications and FR-015–FR-017): the
  allowlist is decoupled from the `/session` and `/chat` request-time origin
  checks and governs embedding only. No schema or config-schema change is
  required (see plan.md).
