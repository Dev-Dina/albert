# DECISIONS.md — Architecture Decision Records

Owner B decisions for the Albert concierge backend.

---

## ADR-001: Classifier Choice

| Option | Latency | Accuracy | Cost |
|--------|---------|----------|------|
| Rule-based keyword matching | ~1ms | ~70% | Free |
| Fine-tuned intent classifier (model-server `/classify`) | ~80ms | ~92% | Low |
| LLM-as-classifier (Gemini per message) | ~600ms | ~95% | High |

**Production pick**: Fine-tuned intent classifier via model-server.

**Reason**: Best latency/accuracy tradeoff — 92% accuracy at 80ms keeps simple queries fast without the per-message LLM cost.

---

## ADR-002: RAG Improvement — Before/After hit@5

**Setup**: 15 golden triples across 5 topics (hours, returns, shipping, pricing, contact).

| Approach | hit@5 |
|----------|-------|
| Naive chunking (flat 512-char chunks, cosine similarity only) | 0.53 |
| Parent-child chunking + Cohere rerank | 0.80 |

**Delta**: +0.27 uplift (+51% relative improvement).

**Why it works**: Small child chunks (256 chars) give precise embedding matches; reranking with a cross-encoder re-scores the top-20 candidates using full semantic context, recovering relevant parents that cosine similarity ranked too low.

---

## ADR-003: Router Confidence Threshold

**Chosen threshold**: 0.7

| Threshold | Failure direction | Risk |
|-----------|------------------|------|
| 0.5 | Too aggressive — borderline messages get canned replies | Wrong answer to a real question |
| 0.7 | Conservative — uncertain messages fall back to agent | Slightly higher agent cost |
| 0.9 | Too conservative — almost nothing routed directly | No cost saving |

**Chosen failure direction**: False negative (send to agent) rather than false positive (wrong direct reply).

**Reason**: It is safer to pay the agent cost on an uncertain message than to return a wrong canned answer to a visitor. Agent fallback is invisible to the user; a wrong direct reply damages trust.

---

## ADR-004: Redis Session TTL

**Chosen TTL**: 1800 seconds (30 minutes)

**Reason**: A 30-minute idle window covers the full duration of a typical customer support conversation (median ~8 minutes, 95th percentile ~22 minutes) while ensuring stale sessions do not accumulate in Redis across hours or days. A shorter TTL (e.g. 5 min) would break context for users who pause mid-conversation; a longer TTL (e.g. 24h) wastes memory and increases PII exposure window.

---

## ADR-005: Agent vs Workflow vs Hybrid

| Approach | Pros | Cons |
|----------|------|------|
| Pure workflow (rule-based) | Fast, predictable, cheap | Cannot handle novel questions, no knowledge lookup |
| Pure agent (LLM every message) | Handles anything | Slow, expensive, unpredictable latency |
| Hybrid (router + agent) | Fast for simple cases, smart for complex | Two systems to maintain |

**Chosen**: Hybrid.

**Reason**: The majority of real visitor messages (greetings, farewells, out-of-scope) are predictable and need no LLM. Routing these directly saves cost and latency for the common case. The agent handles only the messages that genuinely need knowledge retrieval or tool use — earning its slot by doing what a workflow cannot.
