# Data Model: Memory and Router

## ConversationSession (Redis)

Stored as a JSON string at key `conv:{tenant_id}:{conversation_id}`.

| Field | Type | Notes |
|-------|------|-------|
| turns | list[ConversationTurn] | Ordered list of exchanges, capped at 10 |
| (TTL) | int (seconds) | Set via `redis_session_ttl`; reset on every write |

**Isolation**: tenant_id is part of the key — cross-tenant access is structurally impossible.

---

## ConversationTurn (in-memory / Redis value)

| Field | Type | Notes |
|-------|------|-------|
| role | "user" \| "assistant" | Who said this |
| content | str | Redacted text (PII removed before write) |

---

## RouterDecision (in-memory, not persisted)

| Field | Type | Notes |
|-------|------|-------|
| action | "agent" \| "direct" | What to do with this message |
| reply | str \| None | Set only when action == "direct" |
| label | str | Raw classifier label |
| confidence | float | Classifier confidence score |
| routed_to | "router" \| "agent" | For response telemetry |

---

## ToolSelectionExample (eval dataset)

Stored as JSONL at `evals/tool_selection.jsonl`.

| Field | Type | Notes |
|-------|------|-------|
| message | str | Visitor message |
| expected_tool | str \| null | Tool name (`rag_search`, `capture_lead`, `escalate`) or null (direct answer, no tool) |

---

## Config additions (settings)

| Setting | Type | Default | Notes |
|---------|------|---------|-------|
| redis_session_ttl | int | 1800 | Seconds of inactivity before session expires |
| router_confidence_threshold | float | 0.7 | Below this → hand off to agent |
