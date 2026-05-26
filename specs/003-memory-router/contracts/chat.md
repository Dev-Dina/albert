# Contract: POST /chat

## Endpoint

`POST /chat`

## Request

```json
{
  "conversation_id": "string (UUID)",
  "message": "string"
}
```

**Headers**:
- `X-Tenant-Id: <tenant_id>` — stub auth; will be replaced with JWT when auth is delivered

## Response (200)

```json
{
  "reply": "string",
  "routed_to": "router" | "agent"
}
```

## Error Responses

| Status | Condition |
|--------|-----------|
| 400 | Missing `message` or `conversation_id` |
| 422 | Validation error |
| 500 | Unhandled internal error |

## Behaviour

1. Load conversation history from memory (empty list if no prior session or session expired)
2. Redact PII from inbound message (stub — passthrough until Owner C delivers)
3. Guardrails pre-check (stub — always passes)
4. Classify message via router
5. If router returns `action="direct"`: reply = router's canned response
6. If router returns `action="agent"`: invoke agent with history + message
7. Guardrails post-check on reply (stub — always passes)
8. Write turn (redacted message + reply) to memory with TTL reset
9. Return `{reply, routed_to}`

## Tenant Isolation

`tenant_id` is extracted from the `X-Tenant-Id` header (will be verified JWT claim post-auth delivery). It is never read from the request body. All downstream memory, agent, and tool calls are scoped to this `tenant_id`.

---

# Contract: memory service

## `load_history(tenant_id, conversation_id) -> list[dict]`

Returns up to 10 most recent turns as `[{"role": "user"|"assistant", "content": str}]`. Returns `[]` on Redis error (graceful degradation).

## `save_turn(tenant_id, conversation_id, user_message, assistant_reply) -> None`

Appends turn to session, trims to last 10 turns, resets TTL. Redacts PII from `user_message` before write. Silently skips on Redis error.

---

# Contract: router service

## `classify_and_route(message, tenant_id) -> RouterDecision`

Calls model-server `/classify`. Returns `RouterDecision`. Falls back to `action="agent"` on any error or low confidence.
