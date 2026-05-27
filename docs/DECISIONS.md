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

---

## ADR-006: Tracing Backend

**Chosen backend**: OpenTelemetry + Jaeger for local/dev tracing.

**Reason**: OpenTelemetry gives vendor-neutral instrumentation and W3C trace-context
propagation across backend, modelserver, guardrails, and backend outbound HTTP calls.
Jaeger all-in-one is lightweight for local demos and exposes the UI at
`http://localhost:16686`.

**Safety policy**:
- Keep existing `X-Request-ID` correlation for logs and app-level debugging.
- Propagate distributed traces with W3C `traceparent`.
- Do not put raw user text, prompts, system prompts, Authorization headers,
  cookies, service tokens, API keys, or raw PII/secrets in span attributes.
- If user-provided text must be represented, use length, hash, category, or
  redaction counts only.

No tracing secrets are needed for local Jaeger. If Albert later exports traces
to a hosted OTLP backend, Owner A should inject exporter credentials through
env/settings rather than code.

---

## ADR-007: LLM Baseline Provider Fallback

**Primary provider**: Gemini for the mandatory zero-shot intent-classifier
baseline.

**Fallback provider**: Groq, only as a separate run if Gemini is unavailable.

**Rule**: Do not mix Gemini and Groq predictions in one final comparison metrics
file. Each run must record provider and model. If a mixed exploratory file is
ever produced, mark it as mixed and exclude it from Phase 5 production-model
decision evidence.

**Secret handling**: `GEMINI_API_KEY` and optional `GROQ_API_KEY` come from
env/settings, with Owner A/Vault injection expected outside local dev. Keys are
never committed, logged, traced, or written to metrics/model cards.

---

## ADR-008: LLM Zero-Shot Routing Baseline Result

**Run**: Gemini `gemini-2.5-flash-lite`, prompt
`intent-zero-shot-v2-balanced-labels`, same 600-item held-out split as the
classical and DL/ONNX baselines.

| Baseline | Macro-F1 | Latency |
|---|---:|---:|
| Classical TF-IDF + LogisticRegression | `0.971762` | `0.0101 ms/item` |
| DL/ONNX TF-IDF + MLPClassifier | `0.9834` | `0.0419 ms/item` |
| Gemini zero-shot | `0.503639` | `1107.26 ms/item` |

The LLM baseline performs well on `spam` (`0.9873` F1) but poorly on
`other_agent` (`0.0325` F1), often mapping project-specific routing fallback
cases to `faq_rag`. This is expected: `other_agent` is an Albert routing
convention, not a naturally obvious semantic intent category.

**Decision impact**: this supports shipping a supervised lean classifier for
visitor-intent routing, not LLM-per-message routing. The formal production model
choice remains recorded in Phase 5.
