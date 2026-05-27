# Feature Specification: Memory and Router

**Feature Branch**: `003-memory-router`

**Created**: 2026-05-26

**Status**: Draft

**Input**: User description: "Memory and Router: Redis conversation memory with PII redaction stub, HTTP classifier router with confidence threshold, full chat flow wiring, and tool-selection eval harness"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Visitor receives a contextually-aware response (Priority: P1)

A visitor sends a message through the business widget. The system stores the conversation history so that follow-up messages reference previous context correctly — the agent "remembers" what was said earlier in the same session without the visitor having to repeat themselves.

**Why this priority**: Context-aware conversation is the baseline for a usable AI concierge. Without memory, every message is treated as a new conversation, making the agent feel broken.

**Independent Test**: Start a conversation, ask "What are your opening hours?", then ask "And on Sundays?". The second reply must reference the context of the first without re-stating it explicitly.

**Acceptance Scenarios**:

1. **Given** a visitor has sent a message, **When** they send a follow-up message in the same session, **Then** the agent's response reflects awareness of the prior exchange.
2. **Given** a conversation session has expired (TTL elapsed), **When** the visitor sends a new message, **Then** the agent treats it as a fresh conversation with no prior context.
3. **Given** a visitor from Tenant A is in a session, **When** their message is processed, **Then** only Tenant A's conversation history is loaded — never another tenant's.

---

### User Story 2 - Simple queries are answered without invoking the full agent (Priority: P2)

A visitor sends a simple, predictable message (e.g., "hello", "what are your hours?", "goodbye"). Instead of running the full AI agent pipeline (which is slower and costs more), the system classifies the message and responds directly with a deterministic answer.

**Why this priority**: Routing common queries away from the agent reduces latency and cost. The majority of real visitor messages fall into a small set of predictable categories.

**Independent Test**: Send "hello" and confirm the response arrives faster than a full agent response and does not invoke the RAG retrieval pipeline.

**Acceptance Scenarios**:

1. **Given** a message classified as a greeting, **When** the router processes it, **Then** a direct response is returned without engaging the agent.
2. **Given** a message the classifier is uncertain about (low confidence or ambiguous label), **When** the router processes it, **Then** the message is passed to the full agent pipeline.
3. **Given** a message that requires knowledge lookup, **When** the router processes it, **Then** the agent is invoked with the full RAG pipeline.

---

### User Story 3 - Team can measure tool-selection accuracy (Priority: P2)

The engineering team can run an evaluation script against a set of labelled examples to verify the agent picks the right tool (or no tool) for a given message. The eval blocks CI if accuracy drops below threshold.

**Why this priority**: Tool-selection errors are silent bugs — the agent answers but with the wrong behavior. An automated eval catches regressions before they reach production.

**Independent Test**: Run the eval script against 15 labelled examples, confirm it prints per-example pass/fail and an overall accuracy score, and confirm it exits non-zero when accuracy is below the threshold.

**Acceptance Scenarios**:

1. **Given** 15 labelled message→tool examples, **When** the eval script runs, **Then** it reports accuracy and a pass/fail per example.
2. **Given** accuracy drops below the threshold, **When** the eval script runs, **Then** it exits with a non-zero code, blocking CI.
3. **Given** a message correctly answered without any tool, **When** the eval checks it, **Then** "no tool" is treated as a valid expected outcome.

---

### Edge Cases

- What happens when the session store is unavailable? The system must continue processing the message and return a response (degraded, no memory) rather than failing the request.
- What happens when the classifier service is unreachable? The router must fall back to the full agent pipeline rather than returning an error to the visitor.
- What happens when conversation history exceeds the context window limit? Only the most recent N turns are loaded; oldest turns are dropped silently.
- What happens when a message contains PII (name, email, phone)? PII is redacted before writing to session storage; the original unredacted message is passed to the agent within the same request only.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST store conversation turns (visitor message + agent reply) keyed by tenant and conversation identifier with an expiry time.
- **FR-002**: System MUST load prior conversation turns at the start of each request and pass them to the agent as context.
- **FR-003**: System MUST redact personally identifiable information from conversation turns before persisting them to session storage.
- **FR-004**: System MUST classify each inbound message and route it: simple/deterministic labels get a direct response; ambiguous or complex labels go to the agent.
- **FR-005**: Router MUST fall back to the full agent pipeline if the classifier service is unreachable or returns below-threshold confidence.
- **FR-006**: System MUST enforce tenant isolation — no tenant's conversation history may be accessible to another tenant.
- **FR-007**: Conversation sessions MUST expire automatically after a configurable idle period.
- **FR-008**: The full chat flow MUST apply guardrails before passing the message to the router/agent and again before returning the response to the visitor.
- **FR-009**: System MUST provide an evaluation dataset of at least 15 labelled message→tool examples covering both tool-use and no-tool cases.
- **FR-010**: An evaluation script MUST compute tool-selection accuracy and exit non-zero if accuracy falls below a defined threshold.

### Key Entities

- **ConversationSession**: A scoped set of turns belonging to one visitor within one tenant, identified by `tenant_id` + `conversation_id`. Has a TTL.
- **ConversationTurn**: A single exchange — visitor message (redacted for storage) and agent reply. Ordered within a session.
- **RouterDecision**: The outcome of classifying a message — label, confidence score, and the action taken (direct reply or agent handoff).
- **ToolSelectionExample**: A labelled pair of `{message, expected_tool}` used for offline evaluation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Follow-up questions in the same session are answered with correct context reference 100% of the time in manual testing.
- **SC-002**: Simple/deterministic queries (greetings, farewells, FAQ) are handled without invoking the agent in at least 80% of qualifying cases.
- **SC-003**: Router fallback triggers correctly in 100% of cases when the classifier is unreachable or confidence is below threshold.
- **SC-004**: Tool-selection eval accuracy is ≥ 80% on the 15-example golden set; CI blocks on lower scores.
- **SC-005**: Session expiry works correctly — expired sessions return no prior context.
- **SC-006**: No conversation data from Tenant A is ever returned in a Tenant B session (zero cross-tenant leakage in isolation tests).

## Assumptions

- The classifier service (model-server `/classify`) is owned by another team member and may not be running locally; the router must degrade gracefully when it is unavailable.
- PII redaction logic (Owner C's redactor) is not yet delivered; a stub (`redacted = message`) is used and will be swapped when the real redactor is available.
- Conversation history is capped at the last 10 turns per session to stay within LLM context limits.
- The session TTL defaults to 30 minutes of inactivity; this is configurable via settings.
- Guardrails service (pre- and post-check) may also be stubbed if not yet available from other owners.
- `capture_lead` and `escalate` tools remain stubs until Owner A delivers Lead/Conversation models.
- The eval threshold for tool-selection accuracy is 80% (12/15 correct).
