# Research: Memory and Router

## Decision 1: Redis key structure for conversation sessions

**Decision**: `conv:{tenant_id}:{conversation_id}` as a single string key storing a JSON list of turns.

**Rationale**: Prefix-scoped keys make cross-tenant isolation trivially auditable — a key can never belong to two tenants. JSON list is simple, readable, and supports slicing to the last N turns without extra data structures. Using a single key with `SETEX` atomically resets the TTL on every write.

**Alternatives considered**:
- Redis List (LPUSH/LRANGE): More native but TTL reset requires an extra `EXPIRE` call and LRANGE output needs transformation to dict format. Rejected for added complexity.
- Hash per session: Each turn as a field. Harder to enforce max-turn cap and TTL. Rejected.
- PostgreSQL conversation table: Durable but adds DB round-trip to every message. Session memory is ephemeral by design. Rejected.

---

## Decision 2: Router confidence threshold and fallback

**Decision**: Default threshold `0.7`. Any label below threshold OR the literal label `"ambiguous"` hands off to the agent.

**Rationale**: 0.7 is a standard industry default for intent classifiers — high enough to avoid false positives on common phrases, low enough to not over-route to the agent. The `"ambiguous"` label is an explicit escape hatch the model-server can return when it genuinely cannot classify.

**Alternatives considered**:
- Threshold 0.5: Too aggressive; too many borderline messages get direct replies that might be wrong. Rejected.
- No threshold (always trust the label): Dangerous — a mislabelled complex question would get a canned reply. Rejected.

---

## Decision 3: PII redaction stub strategy

**Decision**: `_redact(text: str) -> str` function in `memory.py` that returns text unchanged. A `# TODO: swap with Owner C's redactor` comment marks the seam.

**Rationale**: The spec requires PII redaction before storage but Owner C has not delivered the redactor yet. The stub keeps the contract correct (redacted text is what gets written to Redis) while unblocking Wednesday's work. Swapping is a one-line change.

**Alternatives considered**:
- Skip redaction entirely until Owner C delivers: Violates FR-003 in the spec and could result in raw PII in Redis if the stub is forgotten. Using the stub function makes the seam explicit and forces the swap. Rejected.

---

## Decision 4: Router label map (deterministic responses)

**Decision**: Three labels get direct replies (`greeting`, `farewell`, `out_of_scope`); everything else routes to agent.

**Rationale**: These three cover the most common "no-knowledge-needed" exchanges. Keeping the map small reduces the risk of incorrectly short-circuiting a complex question.

**Alternatives considered**:
- Larger label set (10+ labels): Requires more golden examples to validate and more surface area for mislabelling. Deferred to future iteration.

---

## Decision 5: Tool-selection eval approach

**Decision**: Static replay — each golden example has `{"message": str, "expected_tool": str|null}`. The eval script calls the agent with a mocked LLM that injects a known first-tool-call response, then checks if the right tool was dispatched.

**Rationale**: The agent loop's `_dispatch_tool` is the measurable unit — we care whether the right function was called, not whether the LLM response was good. Mocking the LLM makes the test deterministic and fast (no live API calls in CI).

**Alternatives considered**:
- Live LLM calls in eval: Non-deterministic, costs tokens, slow in CI. Rejected for this eval; live evals are appropriate for faithfulness/relevancy (already in rag_eval.py).
