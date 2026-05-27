# Contract — Modelserver API

**Owner**: Dina — Owner C: Models, Security & Guardrails.

Wire contract for the modelserver sidecar. Normative rationale (labels, threshold, lean-serving, hash check) lives in [`models_security_guardrails_SPEC.md`](../../models_security_guardrails_SPEC.md) §4–§5; this file pins only the concrete shape. Base URL: `settings.modelserver_url` (default `http://modelserver:8020`).

## Auth & headers (WS1/WS2 — implemented)

| Header | Required | Notes |
|--------|----------|-------|
| `Authorization: Bearer <service credential>` | Yes (all except `/health`) | Verified with `hmac.compare_digest`; missing/wrong/unset ⇒ **401**. Internal **service** identity only — **not** tenant identity. |
| `X-Request-ID` | Propagated | Attached by the backend inference client for end-to-end tracing; generated at the edge if absent. |

**No `tenant_id`** appears in any modelserver request — not in body, query, or headers. Model-facing input is untrusted text only; any `tenant_id` in input or model output is ignored.

## `GET /health` — public
Returns liveness/identity. Target (WS4) additionally reports model state:
```json
{ "status": "ok", "service": "modelserver", "app": "albert",
  "model_version": "<str>", "artifact_sha256": "<str>", "loaded": true }
```

## `POST /predict` — current (auth-protected)
Placeholder today: ignores the body and returns `{"label":"unknown","confidence":0.0}`. Auth is enforced. **Retained** after the alias lands (no rename).

## `POST /classify` — target alias (WS3, additive)
Added alongside `/predict` (same handler); `/predict` is **kept**, not renamed.

**Request**
```json
{ "text": "string (required, non-empty, bounded length)",
  "context": { "optional": "non-sensitive routing hints only" } }
```

**Response** (WS4)
```json
{ "label": "faq_rag | lead_capture | human_escalate | spam | other_agent",
  "confidence": 0.0,
  "model_version": "string",
  "artifact_sha256": "string" }
```

## Classifier behavior (WS4)
- `confidence ≥ 0.70` → return the predicted label.
- `confidence < 0.70` → return `other_agent` (abstain); never guess a high-stakes label below threshold.
- `0.70` is the accepted starting threshold (decision O-8), reconciled with the root `eval_thresholds.yaml`.

## Model card & artifact integrity (WS4)
- `modelserver/MODEL_CARD.md` documents task, dataset source + SHA-256, held-out split identity, metrics, and the served **artifact SHA-256**.
- It compares the three required baselines on the same held-out test set: classical ML, DL/ONNX, and LLM zero-shot.
- It reports macro-F1, per-class F1, latency, cost, artifact size, dependency/runtime impact, and the selected production model with rationale.
- At boot the modelserver computes the loaded artifact's SHA-256 and compares it to a pinned value; **mismatch ⇒ refuse to serve** (fail closed, `/health.loaded = false`).

## Constraints
- Serving image: FastAPI + uvicorn + sklearn/onnxruntime only — **no torch/transformers**.
- Fail closed on auth and on artifact-hash mismatch.
