# Tasks — Feature 003 Model Safety & Guardrails

**Owner**: Dina — Owner C: Models, Security & Guardrails · **Branch**: Dina's single Owner C branch.

Tasks are grouped by the seven Owner C workstreams (each notes its phase). Checked items are **merged**. Each remaining task lists its acceptance check and the proving tests. CI tasks conform to [`001 ci-gate.contract.md`](../001-widget-auth-admin-cicd/contracts/ci-gate.contract.md).

## Workstream 1 — Service-to-service auth — Phase 1 ✅ (merged)
- [x] **T1.1** Bearer-auth dependency in `modelserver/app/auth.py` + `guardrails/app/auth.py` (`hmac.compare_digest`, fail-closed 401, token from env, never logged).
- [x] **T1.2** Apply dependency to `/predict`, `/check-input`, `/check-output`; keep `/health` public.
- [x] **T1.3** Backend `inference_client.service_auth_headers()` attaches Bearer from `settings.service_auth_token`.
- [x] **T1.4** Tests: missing/wrong/malformed/correct token; fail-closed-on-unset; health public. *(modelserver 8, guardrails 14, backend client tests)*

## Workstream 2 — Redaction + request tracing — Phase 2 ✅ (merged)
- [x] **T2.1** `backend/app/core/redaction.py`: `redact()` (email, phone, token-like, api-key, Bearer, secret assignments) → text + counts; fail-closed `[REDACTED]`.
- [x] **T2.2** `RedactionFilter` (redacts message, clears `args`) + idempotent `install_redaction_filter()` (no `logging.py` edit).
- [x] **T2.3** `backend/app/core/request_context.py`: `request_id` contextvar, `get_request_id()`, `RequestIdMiddleware` (generate / reuse-safe / reject-unsafe, echo response header).
- [x] **T2.4** `inference_client` attaches `X-Request-ID`; `main.py` wiring (filter install + middleware).
- [x] **T2.5** Tests: fake-API-key not raw, caplog filter redaction, id generate/reuse/reject, client sends both headers. *(backend 27 total)*
- [ ] **T2.6 (follow-up)** Credit-card detector (root SPEC §7 lists it; absent from Phase-2 set).
- [ ] **T2.7 (follow-up)** Exception-traceback redaction (filter covers message, not `exc_info`).
- [ ] **T2.8 (follow-up)** Decide uvicorn access-log handling (outside the app filter; platform/Owner A).

## Workstream 3 — Endpoint contracts and aliases — Phase 3 (planned)
- [ ] **T3.1** Add `/classify` → existing predict handler; keep `/predict`. Same Bearer + `X-Request-ID` behavior.
- [ ] **T3.2** Add `/guardrails/input` + `/guardrails/output` → existing handlers; keep old paths.
- [ ] **T3.3** Tests: alias parity (same shape as old paths); old paths still 200; auth applies to both. **Acceptance:** target names reachable, nothing removed, callers unchanged.
- [ ] **T3.4** Coordinate Owner B/D before any caller migration (out of scope here).

## Workstream 4 — Classifier dataset, training, model card — Phase 4 (planned)
- [ ] **T4.1** Dataset selection for the 5 labels; record source + SHA-256. *(needs decision)*
- [ ] **T4.2** Offline classical ML training script (TF-IDF + LogReg/LinearSVC) → `.joblib`; **no torch/transformers in serving**.
- [ ] **T4.2a** Required DL baseline: train/export offline to ONNX, evaluate via onnxruntime; **no torch/transformers in serving**.
- [ ] **T4.2b** Required LLM zero-shot baseline: offline eval only; record prompt/version/provider/cost assumptions without adding runtime dependency.
- [ ] **T4.3** `modelserver/app/classifier.py` + `schemas.py`: load artifact, predict, `<0.70 → other_agent`; response carries `model_version`, `artifact_sha256`.
- [ ] **T4.4** Boot-time SHA-256 verification; mismatch ⇒ refuse to serve; `/health` reports `model_version`/`artifact_sha256`/`loaded`.
- [ ] **T4.5** `modelserver/MODEL_CARD.md` (task, dataset + SHA-256, held-out split identity, three-model comparison for classical ML vs DL/ONNX vs LLM zero-shot on the same held-out test set, production-model rationale, macro-F1 + per-class F1 + latency + cost, served artifact SHA-256).
- [ ] **T4.6** `evals/classifier/run.py` gating on root `eval_thresholds.yaml` → `classifier.macro_f1_min`. **Acceptance:** classifies lean; threshold abstain; tampered artifact refused; no `tenant_id` in input; F1 ≥ gate; model card includes mandatory same-test-set three-model comparison and production choice.

## Workstream 5 — Guardrails sidecar + tenant/platform rails — Phase 5 (planned)
- [ ] **T5.1** `guardrails/app/rails.py` input rails (injection/jailbreak/cross-tenant/system-prompt-leak) + output rails (PII/secret redaction, leak/cross-tenant block); `schemas.py` (`allowed/action/categories/redacted_text/reason`).
- [ ] **T5.2** Enforce precedence via `guardrail_floor.enforce_floor()`: platform DENY > tenant ALLOW; tenant rails may only narrow.
- [ ] **T5.3** Tests: platform DENY overrides tenant ALLOW; rails block each category; fake `tenant_id` never trusted. **Acceptance:** platform rails always-on; tenant config cannot weaken them.

## Workstream 6 — Red-team + redaction eval gates — Phase 6 (planned)
- [ ] **T6.1** `evals/redteam_cross_tenant/run.py` (7 categories) + `evals/redaction/run.py`; fixtures. **Acceptance:** each category blocked/redacted; redaction leak = 0 across responses, logs, traces, memory, and error outputs; gates = 1.00 locally.
- [ ] **T6.2** Make each `evals/<gate>/run.py` emit `GATE=… STATUS=… OBSERVED=… THRESHOLD=…`, exit 0/1/2, append to results jsonl (per `001` contract).
- [ ] **T6.3** Confirm canonical root `eval_thresholds.yaml` Owner C keys; `validate_thresholds` keeps redteam/redaction = 1.00. `evals/eval_thresholds.yaml` is legacy RAG/router data and must not be used for Owner C gates.
- [ ] **T6.4** No-heavy-dep CI assertion: serving lockfiles free of torch/transformers.
- [ ] **T6.5** Owner D wires gates into `.github/workflows/ci.yml` (protected — coordinate, do not edit unilaterally). **Acceptance:** gates run on PR/main; red on any safety regression.

## Workstream 7 — Served-model hardening if needed — Phase 7 (conditional)
- [ ] **T7.1** If Phase 4 selects DL/ONNX for serving, harden the ONNX artifact/runtime path (no torch/transformers in image).
- [ ] **T7.2** Confirm `MODEL_CARD.md` served-choice rationale still references the completed Phase 4 classical ML vs DL/ONNX vs LLM zero-shot comparison.
