# Feature Specification: Agent LLM Adapter, Tool Stubs, and Bounded Agent Loop

**Feature Branch**: `001-agent-llm-tools`

**Created**: 2026-05-26

**Status**: Draft

**Input**: User description: "Owner B — Agent LLM adapter up, tool stubs (rag_search, capture_lead, escalate), bounded agent loop with auto-escalation, and system prompt template."

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Visitor asks a business question (Priority: P1)

A visitor on a business's embedded widget sends a question. The AI concierge searches the tenant's knowledge base, finds a relevant answer, and replies — all within a single turn.

**Why this priority**: This is the core value of the product. Without it nothing else matters.

**Independent Test**: Send a test message to the agent endpoint, observe that the agent calls `rag_search` and returns a non-empty reply.

**Acceptance Scenarios**:

1. **Given** a visitor sends "What are your opening hours?", **When** the agent processes the message, **Then** it calls `rag_search` with a relevant query and returns a reply based on the result.
2. **Given** `rag_search` returns no useful results, **When** the agent processes the message, **Then** it replies honestly that it does not have that information and offers to escalate.

---

### User Story 2 — Agent hits iteration limit and auto-escalates (Priority: P2)

The agent cannot resolve the visitor's request within the allowed number of tool-call rounds. It automatically escalates rather than looping forever or returning a broken response.

**Why this priority**: Prevents runaway loops and ensures the visitor always gets a response.

**Independent Test**: Configure `max_iterations = 1`, send a message that requires multiple tool calls, verify the agent returns an escalation reply.

**Acceptance Scenarios**:

1. **Given** `max_iterations = 5` and the agent has used all 5 iterations, **When** the loop exits, **Then** the agent returns a polite escalation message and sets `escalated = true`.
2. **Given** the LLM returns an unexpected finish reason, **When** the loop detects it, **Then** the agent escalates automatically without raising an unhandled exception.

---

### User Story 3 — Visitor provides contact details (Priority: P3)

A visitor expresses interest and provides their name and email. The agent captures the lead scoped to the correct tenant.

**Why this priority**: Lead capture is a key business outcome but depends on Owner A's models being delivered first.

**Independent Test**: Once `capture_lead` tool is wired, send a message containing contact details, verify a lead row is written with the correct `tenant_id`.

**Acceptance Scenarios**:

1. **Given** a visitor says "My name is Sara, email sara@example.com", **When** the agent decides to capture a lead, **Then** `capture_lead` is called with `tenant_id` from the verified session — never from the request body.
2. **Given** the lead capture fails (e.g. DB error), **When** the tool returns an error, **Then** the agent informs the visitor and continues the conversation without crashing.

---

### User Story 4 — Visitor requests a human agent (Priority: P3)

A visitor explicitly asks to speak to a person. The agent calls `escalate`, writes a flag to `conversation_flags`, and returns a handoff message.

**Why this priority**: Depends on Owner A's `conversation_flags` model; blocked until that is delivered.

**Independent Test**: Once `escalate` tool is wired, send "I want to speak to a human", verify `conversation_flags` row is created and `escalated = true` is returned.

**Acceptance Scenarios**:

1. **Given** a visitor says "Can I speak to someone?", **When** the agent processes the message, **Then** `escalate` is called and the reply confirms the handoff.

---

### Edge Cases

- What happens when the LLM API is unreachable? The adapter must surface the error without hanging; the caller receives a clear exception.
- What happens when `rag_search` returns an empty list? The agent must still produce a sensible reply.
- What happens when tool arguments from the LLM are malformed JSON? The dispatch layer must catch the parse error and return an error result to the LLM rather than crashing.
- What happens when `tenant_id` is missing or empty? The adapter and tools must reject the call immediately.
- What happens when the system prompt template is missing from disk? The agent must fail fast at startup, not at request time.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide an async LLM client wrapper that accepts `tenant_id` on every call for cost attribution logging.
- **FR-002**: The LLM API key MUST be fetched from Vault at startup; a config fallback is permitted for local development only.
- **FR-003**: The system MUST expose a `rag_search` tool with a defined schema (name, description, parameters) that the LLM can call.
- **FR-004**: The system MUST expose a `capture_lead` tool stub with a Pydantic args schema, rate-limit skeleton, and tenant-scoped write skeleton.
- **FR-005**: The system MUST expose an `escalate` tool stub that writes to a `conversation_flags` table.
- **FR-006**: The agent loop MUST be bounded: `max_iterations = 5`, `max_tokens_per_turn` configurable via settings.
- **FR-007**: When `max_iterations` is exceeded, the agent MUST auto-escalate and return `escalated = true` in the result.
- **FR-008**: The system prompt MUST be a version-controlled Jinja2 template with at minimum a `{{ persona }}` injection point.
- **FR-009**: `tenant_id` MUST come from the verified session/auth context — never from the visitor's request body.
- **FR-010**: The tool list format MUST be documented and stable so Owner C can wire the classifier result into the router.

### Key Entities

- **LLMAdapter**: Wraps the Groq async client; holds no tenant state itself; accepts `tenant_id` per call.
- **AgentResult**: Return value of one agent turn — contains `reply`, `escalated`, `iterations_used`, `tool_calls`.
- **Tool definition**: A dict with `type: "function"` and a `function` block (name, description, parameters) — the format passed to the LLM.
- **System prompt template**: Jinja2 `.j2` file; variables: `persona`, `business_name`, `max_iterations`.

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A visitor message results in an agent reply within a single request, with at least one `rag_search` tool call visible in the result's `tool_calls` list.
- **SC-002**: When `max_iterations` is set to 1 and the task requires more turns, the agent returns `escalated = true` without raising an exception.
- **SC-003**: The end-to-end integration test (mock LLM) passes in CI with zero flaky runs across 10 consecutive runs.
- **SC-004**: No `tenant_id` value is ever read from a visitor-supplied request body in any tool or service in this feature.
- **SC-005**: The LLM API key is never logged or written to any file; it is read from Vault (or config fallback) at startup only.

---

## Assumptions

- Owner A will deliver `get_current_tenant`, `Conversation`, and `Lead` models before `capture_lead` and `escalate` are fully wired.
- The Groq API (`llama-3.3-70b-versatile`) supports the OpenAI tool-call format used here.
- `capture_lead` and `escalate` tools are stubs in this feature; full logic is a follow-on task once Owner A delivers.
- The system prompt template is the single source of truth for persona/tone; tenant admins do not override it in this phase.
- Mobile/widget embedding is out of scope for this feature — this feature covers the backend agent loop only.
- A mock LLM is acceptable for the integration test; no real API calls are made in CI.
