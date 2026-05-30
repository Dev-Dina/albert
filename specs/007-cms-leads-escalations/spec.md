# Feature Specification: CMS Content, Lead Lifecycle & Escalation Capture

**Feature Branch**: `007-cms-leads-escalations`

**Created**: 2026-05-30

**Status**: Draft

**Input**: User description: "CMS content authoring + lead lifecycle management + escalation capture for the Albert multi-tenant concierge. Closes three related admin/data gaps, all strictly tenant-scoped (RLS-enforced, never trust client tenant_id)."

## Overview

This feature closes three related gaps in the business-admin experience of the
multi-tenant concierge. All three share the same non-negotiable property:
**every record and every read is scoped to the acting tenant**, with tenant
identity taken only from the authenticated admin session — never from a value
supplied by the client.

1. **Content authoring (CMS)** — Business admins currently have no way to give
   the AI agent knowledge. The retrieval pipeline can only serve seed data
   because the content source returns nothing. Admins need to author the content
   their widget agent answers from.
2. **Lead lifecycle** — Captured leads land in a single undifferentiated state
   with no way to progress or triage them. Admins need to move a lead through a
   defined sales/contact lifecycle.
3. **Escalation capture** — When the agent hands a conversation to a human, the
   reason and context are discarded. Admins need a durable record and a place to
   review escalated conversations.

## Clarifications

### Session 2026-05-30

- Q: What lead status lifecycle and transition rules should the system enforce? → A: Forward + lost (strict): `new → contacted → qualified → won`; `lost` reachable from any non-terminal state; `won`/`lost` terminal; backward moves rejected.
- Q: When an admin creates/edits/deletes content, when should the agent's retrievable knowledge be updated? → A: Background after save — the save returns immediately and chunking/embedding/indexing runs as a background task that converges within ~seconds to one minute.
- Q: What maximum content body length should the CMS accept per page? → A: 100,000 characters (empty/whitespace bodies rejected).
- Q: How should escalation records relate to a conversation escalated more than once? → A: One escalation record per conversation (1:1); re-escalation updates the existing reason/summary/timestamp.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Author content the agent answers from (Priority: P1)

A business admin signs in to the admin console, creates one or more content
pages (a title and a body of text — e.g. an FAQ, a policy, a product
description), and saves them. The system makes that content available to the
business's widget agent so that a visitor asking a related question receives an
answer grounded in the admin's authored content. The admin can later edit or
delete a page, and the agent's answers reflect the change.

**Why this priority**: Without authored content the agent has nothing
tenant-specific to retrieve, so the core product promise (an AI concierge that
knows *this* business) cannot be delivered for any customer beyond the seed
demo. This unblocks real customer value and is the foundation the other two
stories build trust on.

**Independent Test**: Sign in as a business admin, create a page with distinctive
text, and confirm via the widget (or a retrieval check) that a related visitor
question surfaces that text. Editing the page changes the answer; deleting it
removes the text from answers. Fully demonstrable on its own.

**Acceptance Scenarios**:

1. **Given** an authenticated admin for Tenant A with no content, **When** they
   create a content page with a title and body and save it, **Then** the page is
   stored against Tenant A and becomes retrievable by Tenant A's agent.
2. **Given** a saved content page, **When** the admin edits its body and saves,
   **Then** the agent's retrievable knowledge reflects the new body and no longer
   reflects the old body.
3. **Given** a saved content page, **When** the admin deletes it, **Then** the
   page no longer appears in the admin's content list and its text is no longer
   retrievable by the agent.
4. **Given** admins for Tenant A and Tenant B, **When** Tenant A creates content,
   **Then** Tenant B cannot list, read, edit, delete, or retrieve Tenant A's
   content, and Tenant B's agent never surfaces Tenant A's content.
5. **Given** an admin creates a page with an empty body, **When** they save,
   **Then** the system rejects it with a clear validation message (no empty
   content is indexed).

---

### User Story 2 - Progress a lead through its lifecycle (Priority: P2)

A business admin opens the leads list, selects a captured lead, reviews its
details (name, contact, intent, originating conversation, current status), and
advances its status along a defined lifecycle (for example from "new" to
"contacted" to "qualified", or marking it "won" or "lost"). The system accepts
only valid transitions and records the change so the admin can triage and
report on their pipeline.

**Why this priority**: Leads are already captured but stuck in a single state,
so the admin cannot act on or report against them. A defined lifecycle turns raw
captures into a usable pipeline. It depends on no other story and delivers
standalone value once content authoring exists.

**Independent Test**: Sign in as an admin, open an existing lead, change its
status to an allowed next state, and confirm the new status persists and is
reflected in the list and its status filter. Attempting a disallowed transition
is rejected.

**Acceptance Scenarios**:

1. **Given** a lead in status "new" for Tenant A, **When** the admin sets it to
   an allowed next status, **Then** the change persists and is shown in the lead
   detail and list.
2. **Given** a lead in a given status, **When** the admin attempts a transition
   that is not allowed by the lifecycle, **Then** the system rejects it with a
   clear message and the status is unchanged.
3. **Given** a lead belonging to Tenant B, **When** a Tenant A admin attempts to
   view or change it, **Then** the system denies access and reveals nothing about
   the lead's existence.
4. **Given** leads in various statuses, **When** the admin filters the list by
   status, **Then** only leads in that status for their tenant are shown.

---

### User Story 3 - Capture and review escalations (Priority: P3)

When the agent escalates a conversation to a human, the system stores the
escalation reason and context summary alongside the conversation. A business
admin can open an "escalations" view, see the list of escalated conversations
for their business, and read the reason and summary for each so a human can
follow up with full context.

**Why this priority**: Escalation already flags conversations, but the *why* is
lost, so human follow-up starts blind. Persisting and surfacing the reason is a
contained, high-leverage improvement, but it affects fewer flows than content or
leads, so it is sequenced last.

**Independent Test**: Trigger an escalation in a conversation, then sign in as
the admin and confirm the escalated conversation appears in the escalations view
with the captured reason and summary. Confirm another tenant cannot see it.

**Acceptance Scenarios**:

1. **Given** an active conversation for Tenant A, **When** the agent escalates it
   with a reason and summary, **Then** the conversation is marked escalated and
   the reason and summary are persisted against Tenant A.
2. **Given** one or more escalated conversations, **When** the Tenant A admin
   opens the escalations view, **Then** they see each escalated conversation with
   its reason and summary.
3. **Given** an escalation captured for Tenant B, **When** a Tenant A admin views
   their escalations, **Then** Tenant B's escalation is never shown.
4. **Given** an escalation is triggered with a reason but no summary, **When** it
   is persisted, **Then** the reason is stored and the missing summary is handled
   gracefully (recorded as empty, not an error).

---

### Edge Cases

- **Re-indexing on change**: When content is created, edited, or deleted, the
  agent's retrievable knowledge must converge (within ~1 minute, via the
  background indexing task) to the new state; stale chunks from a prior version of
  a page must not be retrievable.
- **Indexing failure after save**: If background indexing fails after a
  successful save, the saved content is preserved and the failure is observable
  (logged/retryable); the admin's save is not lost.
- **Large content body**: Content bodies must be accepted up to 100,000
  characters and split for retrieval without loss; bodies beyond the limit are
  rejected with a clear message.
- **Concurrent edits**: Two admins of the same tenant editing the same page — the
  last successful save wins and the indexed knowledge matches the persisted body.
- **Duplicate/idempotent escalation**: Escalating an already-escalated
  conversation updates/keeps a single coherent record rather than producing
  conflicting duplicates.
- **Lead with no originating conversation**: A lead whose conversation link is
  absent still supports full lifecycle transitions.
- **Invalid status value**: A status value outside the defined lifecycle is
  rejected for both leads and (where applicable) conversation state.
- **Empty tenant**: An admin with no content / no leads / no escalations sees an
  explicit empty state, not an error.

## Requirements *(mandatory)*

### Functional Requirements

#### Tenant isolation (applies to all stories)

- **FR-001**: System MUST scope every content page, lead, and escalation record
  to exactly one tenant, and MUST derive the acting tenant solely from the
  authenticated admin session (or, for agent-driven escalation, the verified
  conversation/session context) — never from a client-supplied tenant identifier.
- **FR-002**: System MUST prevent any tenant from listing, reading, modifying,
  deleting, or retrieving another tenant's content, leads, or escalations,
  including via the agent's retrieval path, and MUST not disclose the existence of
  another tenant's records.
- **FR-003**: System MUST enforce tenant scoping at the data-store level (defense
  in depth) in addition to application-layer checks.

#### Content authoring (Story 1)

- **FR-010**: Business admins MUST be able to create a content page consisting of
  a title and a body.
- **FR-011**: Business admins MUST be able to view a list of their tenant's
  content pages and open an individual page.
- **FR-012**: Business admins MUST be able to edit the title and body of an
  existing content page.
- **FR-013**: Business admins MUST be able to delete a content page.
- **FR-014**: System MUST reject a content page with an empty or whitespace-only
  body, and MUST enforce a maximum body length of 100,000 characters, returning a
  clear validation message in each case.
- **FR-015**: System MUST make authored content available to the tenant's agent
  retrieval pipeline (replacing the current empty content source), so that
  visitor questions can be answered from authored content.
- **FR-016**: System MUST update retrievable knowledge to reflect content
  create/edit/delete so that deleted or superseded content is no longer
  retrievable. Indexing MUST run as a background task triggered by the save: the
  admin save operation returns without waiting for embedding/indexing to
  complete, and retrievable knowledge converges to the new state within
  approximately one minute.
- **FR-017**: System MUST attribute any processing cost of indexing content to the
  owning tenant (consistent with existing cost attribution).

#### Lead lifecycle (Story 2)

- **FR-020**: System MUST define the lead lifecycle as the fixed states `new`,
  `contacted`, `qualified`, `won`, and `lost`, with these allowed transitions:
  `new → contacted`, `contacted → qualified`, `qualified → won`, and any
  non-terminal state (`new`, `contacted`, `qualified`) → `lost`. `won` and `lost`
  are terminal (no outgoing transitions). Backward transitions are not allowed.
- **FR-021**: Business admins MUST be able to view a lead's details including its
  current status.
- **FR-022**: Business admins MUST be able to change a lead's status, and the
  system MUST accept only transitions permitted by the defined lifecycle,
  rejecting others with a clear message.
- **FR-023**: System MUST persist the updated status and reflect it in the lead
  list and status filter.
- **FR-024**: System MUST record when a lead's status last changed.

#### Escalation capture (Story 3)

- **FR-030**: System MUST persist the escalation reason (required) and summary
  (optional) when a conversation is escalated, associated with that conversation
  and tenant.
- **FR-031**: System MUST continue to mark the conversation as escalated.
- **FR-032**: Business admins MUST be able to view a list of their tenant's
  escalated conversations and read each one's reason and summary.
- **FR-033**: System MUST handle an escalation with a missing summary gracefully
  (store empty, not error) and MUST validate the reason is present and within
  length limits.
- **FR-034**: There MUST be at most one escalation record per conversation (1:1).
  Re-escalation of an already-escalated conversation MUST update the existing
  record's reason, summary, and timestamp rather than creating a second record.

### Key Entities *(include if feature involves data)*

- **Content Page**: A unit of tenant-authored knowledge the agent can answer
  from. Attributes: owning tenant, title, body, timestamps. Belongs to exactly
  one tenant. Source for the retrieval/indexing pipeline.
- **Lead**: An existing entity (visitor lead captured in a conversation).
  Extended by this feature with a constrained lifecycle status and a
  status-changed timestamp. Belongs to exactly one tenant; may reference an
  originating conversation.
- **Escalation**: The captured context of a human-handoff event for a
  conversation. Attributes: owning tenant, referenced conversation, reason
  (required), summary (optional), timestamp. Belongs to exactly one tenant and to
  exactly one conversation (at most one escalation record per conversation;
  re-escalation updates it).
- **Conversation**: An existing entity; this feature relies on its escalated
  status and links the Escalation record to it.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A business admin can author a new content page and, within one
  minute of saving, a related visitor question to that business's widget returns
  an answer grounded in the new content.
- **SC-002**: After an admin deletes a content page, the deleted text no longer
  appears in any agent answer for that business.
- **SC-003**: In cross-tenant tests, 100% of attempts by one tenant to read or
  retrieve another tenant's content, leads, or escalations are denied, with no
  leakage in agent answers.
- **SC-004**: A business admin can change a lead's status in under 30 seconds, and
  100% of disallowed lifecycle transitions are rejected.
- **SC-005**: 100% of escalations triggered by the agent result in a stored,
  admin-viewable reason; the reason/summary loss rate is 0%.
- **SC-006**: A business admin can locate and read the full context of an
  escalated conversation from the admin console without engineering assistance.

## Assumptions

- **Content model scope (v1)**: A content page is plain title + body text. Rich
  media, file/URL crawling, and versioning/history are out of scope for v1.
  No draft-authoring *workflow/UI* ships in v1: newly created pages default to
  published and are immediately retrievable. The existing `is_published` flag is
  reused and honored by retrieval (only published pages are indexed), so a draft
  state can be introduced later without a schema change; it is simply not exposed
  in the v1 admin UI. (Lead lifecycle, re-index timing, body length, and
  escalation cardinality are no longer assumptions — see Clarifications.)
- **Admin authn/authz reused**: The existing business-admin authentication and
  tenant-resolution mechanism is reused; no new login flow is introduced. Only
  authenticated admins of a tenant can manage that tenant's content, leads, and
  escalations.
- **Admin surface**: Management happens through the existing admin console plus a
  backing tenant-scoped API; the visitor-facing widget is unchanged except that
  the agent now retrieves authored content.
- **Retrieval pipeline reused**: The existing chunking/embedding/retrieval
  pipeline is reused; this feature supplies its content source rather than
  building a new retrieval mechanism.
- **No new heavy serving dependencies**: Indexing reuses existing embedding
  infrastructure; no new heavyweight model dependencies are added to serving
  containers.
- **Escalation review is read-only (v1)**: Admins view escalations and their
  context; assigning, resolving, or replying to escalations is out of scope for
  v1.
