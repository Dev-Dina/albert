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

`gemini-2.5-flash-lite` is the official recorded baseline for this submission.
Earlier `gemini-2.0-flash` references were planning/provider-version references,
not this committed artifact (provider model-lifecycle update — older
experimental/preview model IDs can be superseded). CI does not call Gemini; it
uses the committed evaluation artifacts and the model card.

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

---

## ADR-009: Production Intent Classifier Choice

**Decision**: ship the Classical TF-IDF + LogisticRegression classifier as the
production model for Owner C visitor-intent routing.

**Context**: Phase 4 completed the mandatory same-test-set comparison:

| Model | Macro-F1 | Latency | Serving status |
|---|---:|---:|---|
| Classical TF-IDF + LogisticRegression | `0.971762` | `0.0101 ms/item` | Already served |
| DL/ONNX TF-IDF + MLPClassifier | `0.9834` | `0.0419 ms/item` | Challenger |
| Gemini zero-shot | `0.503639` | `1107.26 ms/item` | Rejected for routing |

**Alternatives considered**:

- **DL/ONNX challenger**: highest macro-F1, but requires serving-path hardening,
  dependency review, and ONNX runtime operational validation before promotion.
- **Gemini zero-shot**: slower, provider-dependent, cost-bearing, and much worse
  on macro-F1; especially weak on `other_agent`.

**Rationale**:

- Strong F1 with fastest latency.
- Already wired into modelserver and protected by artifact SHA-256 verification.
- Lowest operational risk: no network dependency, no provider key, no GPU, no
  `torch`, and no `transformers`.
- Keeps the serving container lean while satisfying the classifier gate.

**Consequence**: the ONNX model remains the challenger and can be promoted later
after serving hardening. Highest F1 did not automatically win; production choice
balances quality, latency, simplicity, and runtime risk.

---

## ADR-010: NeMo Guardrails sidecar with a deterministic platform-deny prefilter

**Decision**: the guardrails sidecar runs **NeMo Guardrails + a deterministic
platform-deny prefilter**. Deterministic platform DENY rules run **first**; NeMo
Guardrails handles the **configurable tenant topical/conversation rails**; redaction
remains service-local and separately CI-gated.

> Supersedes the earlier "deterministic rules-first; NeMo declined" decision. The
> project brief recommends NeMo as the sidecar, so we adopt it — without letting it
> own every safety control.

**Why NeMo was added**: brief compliance. NeMo is the recommended guardrails sidecar;
adopting it makes the architecture honestly NeMo-based for topical/conversation policy.

**Why deterministic DENY rules still run first**:

- The platform protections (prompt-injection, jailbreak, cross-tenant,
  system-prompt extraction, tenant-id override, tool-abuse, secret-extraction) are
  inspectable, cheap, deterministic, and make red-team failures concrete (1.00 gate).
- Running them first short-circuits before NeMo is consulted, so **tenant/topical
  rails can only ADD a block — they can never weaken a platform deny** (the
  tenant-cannot-weaken-platform invariant is structural, not config-dependent).

**Why NeMo runs with no LLM and no embeddings**: the tenant allowed/blocked-topic
policy is enforced by a registered custom Python action (`check_topic_policy`,
deterministic, shared with the fallback matcher in `app/topic_policy.py`). NeMo's
rails engine executes the policy; `models: []` and no embedding provider mean **no
paid LLM calls and no runtime model downloads** in CI.

**Why redaction stays separate**: redaction (`app/redaction.py`) runs last, before
returning/logging, and has its own CI gate (`evals/redaction/run.py`, 1.00). It is
not delegated to NeMo, so PII/secret leakage is verified independently.

**Why NeMo is isolated to the guardrails service**: NeMo's dependency tree
(onnxruntime, fastembed, annoy, pandas) is heavy. It is added **only** to the
guardrails sidecar — never to the backend or modelserver, which stay lean. The
modelserver retains **no torch/transformers** (serving = sklearn + joblib).

**Footprint / size exception**: adding NeMo grows the guardrails image from **373 MB
to 782 MB** (multi-stage build: `g++` only in the builder to compile `annoy`, which
has no cp312 wheel; the runtime ships no compiler). 782 MB exceeds the brief's
<500 MB lean ideal but is within the agreed 800 MB ceiling for this sidecar; it is a
**justified guardrails-sidecar exception** for NeMo compliance, kept because the
red-team, redaction, smoke, and service-auth gates all pass.

**Availability**: in CI/production (`GUARDRAILS_REQUIRE_NEMO=1`, set in the image) a
NeMo load failure **fails loud** — we never silently degrade to deterministic-only
while claiming NeMo. Local dev may fall back gracefully to the deterministic matcher.

**Consequence**: blocks the same platform categories as before (unchanged red-team
behavior) plus NeMo-executed tenant topical policy. Phase 7 remains responsible for
deeper redaction hardening and broader leak-surface coverage.

---

## ADR-011: Redaction Hardening Gate

**Decision**: use a separate `evals/redaction/run.py` gate for planted-value
leak testing, while keeping attack probes in `evals/redteam_cross_tenant/run.py`.

**Context**: redaction must be proven across logs, traces, responses, errors,
eval output, and generated CI artifacts. The redaction threshold is already
canonical in root `eval_thresholds.yaml` as `redaction.required_pass_rate = 1.00`.

**Rationale**:

- A separate gate keeps leak fixtures focused and easier to expand.
- It cleanly distinguishes "attack blocked" from "sensitive value leaked".
- Local runs should print to stdout by default so root `artifacts/` output is
  not generated unless CI passes `--output`.
- Model artifacts under `training/intent_classifier/artifacts/` and
  `modelserver/artifacts/` are not generated CI output and must not be cleaned
  up by redaction work.

**Consequence**: Phase 7B implements the redaction runner, fixtures, and tests
against the full leak-surface contract. Owner D can later wire the same command
with `--output artifacts/ci-gate-results.json` in CI.

---

## ADR-012: Phase 7B Redaction Leak Surfaces

**Decision**: harden redaction with deterministic service-local redactors and
stdout-only eval runners by default.

**Context**: backend already had a log redaction filter, guardrails already
redacted responses, and modelserver had no redaction filter. Phase 7B needed
coverage without a risky cross-service refactor.

**Rationale**:

- Service-local redactors keep the change small and avoid coupling the
  sidecars to backend internals.
- Stable placeholders make test and eval output predictable:
  `[REDACTED_API_KEY]`, `[REDACTED_TOKEN]`, `[REDACTED_EMAIL]`,
  `[REDACTED_PHONE]`, and `[REDACTED_CREDIT_CARD]`.
- Custom OpenTelemetry attributes reject unsafe names and unsafe string values;
  safe numeric summaries such as lengths remain allowed.
- App code does not log raw request bodies. Uvicorn/access-log policy should
  stay no-body/sanitized if configured later.
- Root `artifacts/` is generated local/CI output; default eval runs do not write
  it. CI must opt in with `--output`.

**Consequence**: Phase 7B covers planted fake/provider keys, Bearer/service
tokens, JWT-like strings, emails, phones, credit-card-like strings, generic
token-like strings, app logs, guardrails responses, custom trace attributes,
eval stdout, and optional eval JSON. Phase 8 can wire the commands into CI.

---

## ADR-013: Tenant Erasure — Redis Coverage and Traces/Logs

**Decision**: tenant erasure purges all tenant-scoped Redis keys
(`session:{tenant_id}:*` AND `conv:{tenant_id}:*`) and treats traces/logs as a
no-op because raw sensitive data is never written to them.

**Context**: PROJECT_CONTEXT §11 lists "traces/logs" among the stores erasure
must clear, and conversation memory is written to Redis as
`conv:{tenant_id}:{conversation_id}` (services/memory.py). Earlier erasure only
deleted `session:` keys. Tracing (OpenTelemetry + Jaeger, ADR-006) and logging
record only redacted, non-sensitive attributes — lengths, hashes, categories,
redaction counts — never raw user text, PII, secrets, prompts, Authorization
headers, cookies, or tokens. Local Jaeger is ephemeral with no persistent
tenant-payload store.

**Rationale**:
- Conversation memory is tenant data and must be erased — now covered.
- There is no raw tenant data in traces/logs to delete, so a purge is a no-op;
  redaction-before-emit is the actual control.

**Consequence**: `_erase_redis` scans both `session:` and `conv:` prefixes;
`_erase_traces` is a documented no-op (`summary["traces"] = 0`). If a persistent
trace store holding tenant payloads is ever introduced, it MUST implement tenant
purge and this ADR must be revisited.

---

## ADR-014: Classifier-Driven Cheap Path + Routed-Off-Agent Metric

**Decision**: the router maps each classifier label to a deterministic cheap-path
handler that runs WITHOUT the bounded LLM agent; only ambiguous/open-ended turns
reach the agent.

| Label | Handler | Behaviour (no LLM agent) |
|---|---|---|
| `spam` | drop | rejected before any work |
| `faq_rag` | rag | extractive answer from the tenant's RAG corpus |
| `lead_capture` | lead | `capture_lead` when a contact is present in the message |
| `human_escalate` | escalate | flag the conversation for human handoff |
| `other_agent` / ambiguous / low-confidence / classifier error | agent | bounded tool-calling agent |

**Fallback**: a cheap path that can't complete (no retrieval hit; no extractable
contact) returns `reply=None` and the route falls back to the agent — logged.

**Cost story** (deterministic report `evals/router_cost.py` over the committed
`evals/routing_golden.jsonl`, 15 turns):

- routed off-agent: **12/15 = 80.0%** (drop 13.3%, rag 40.0%, lead 13.3%, escalate 13.3%)
- agent-handled: **3/15 = 20.0%**
- estimated cost saved: **$0.0240** — **ESTIMATE ONLY**, assuming **$0.0020 per
  bounded agent turn avoided** (several LLM calls/turn). This is a documented
  assumption, not a measured bill; replace with real telemetry when available.

**Assumptions / caveats**: the golden set reflects expected classifier labels at
high confidence; the per-turn agent cost is an estimate; embedding cost on the
RAG cheap path is still recorded by `cost_events` (only the LLM agent loop is
avoided). Guardrails input/output checks and tenant persona/rails injection wrap
every path; tenant scoping (RAG, capture_lead, escalate) is unchanged.
