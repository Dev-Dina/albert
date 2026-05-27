# Plan — Feature 003 Model Safety & Guardrails

**Owner**: Dina — Owner C: Models, Security & Guardrails · **Branch**: Dina's single Owner C branch.

Implementation plan for [`spec.md`](./spec.md). The seven workstreams map onto the root SPEC §12 execution phases; workstreams 1–2 are **done and merged**, the rest are planned. One folder, one branch.

## Design approach

- **Two lean sidecars** (`modelserver`, `guardrails`), FastAPI + uvicorn only. Inference uses sklearn/onnxruntime; **no torch/transformers in the serving image**. DL/ONNX work is evaluated offline and only an exported artifact ships if selected.
- **Internal service auth** on every non-`/health` endpoint (Bearer, fail-closed 401), independent of tenant identity. *(done)*
- **Redaction-before-sinks** as a backend utility + logging filter; **request_id** generated at the edge and propagated downstream. *(done)*
- **Additive endpoint aliases** — never a breaking rename; old + new names share handlers until Owner B/D migrate.
- **Guardrails precedence** via `guardrail_floor.enforce_floor()`: tenant config may only narrow; platform DENY wins.
- **CI gates** conform to the `001` runner contract; Owner C thresholds live in the canonical root `eval_thresholds.yaml`.

## Owner C workstreams → phase mapping

| Workstream (Dina — Owner C) | Phase | Status |
|---|---|---|
| WS1 — Service-to-service auth | Phase 1 | **DONE (merged)** |
| WS2 — Redaction + request tracing | Phase 2 | **DONE (merged)** |
| WS3 — Endpoint contracts and aliases | Phase 3 | Planned |
| WS4 — Classifier dataset, training, model card | Phase 4 | Planned |
| WS5 — Guardrails sidecar + tenant/platform rails | Phase 5 | Planned |
| WS6 — Red-team + redaction eval gates | Phase 6 | Planned |
| WS7 — Served-model hardening if needed | Phase 7 | Conditional |

## Phase table

| Phase | Goal | Status |
|------|------|--------|
| 1 — Service-to-service auth | Bearer auth on both services, fail closed; backend attaches credential | **DONE (merged)** |
| 2 — Redaction + tracing | Deterministic redaction before sinks; `request_id`/`X-Request-ID` propagation | **DONE (merged)** |
| 3 — Endpoint aliases (additive) | Add `/classify`, `/guardrails/input`, `/guardrails/output`; keep old paths | Planned |
| 4 — Classifier baseline + model card | Dataset → required classical ML + DL/ONNX + LLM zero-shot comparison → artifact + SHA-256 boot check + `<0.70→other_agent` + MODEL_CARD | Planned |
| 5 — Guardrails + red-team | Real platform/tenant rails; 7 red-team categories + redaction-leak suite | Planned |
| 6 — CI eval gate + demo proof | Wire gates per `001` CI contract; coordinate Owner D | Planned |
| 7 — Served-model hardening if needed | Harden DL/ONNX serving path only if Phase 4 selects it; comparison is not deferrable | Conditional |

## Delivered files (WS1–WS2 / Phases 1–2)

- Auth: `modelserver/app/auth.py`, `guardrails/app/auth.py`, `*/app/main.py` (dependency wiring), `backend/app/clients/inference_client.py` (`service_auth_headers`).
- Redaction/tracing: `backend/app/core/redaction.py`, `backend/app/core/request_context.py`, `backend/app/clients/inference_client.py` (`X-Request-ID`), `backend/app/main.py` (filter install + middleware), with tests under `*/tests/`.

## File map (remaining workstreams)

- **WS3 / Phase 3**: `modelserver/app/main.py`, `guardrails/app/main.py` (alias routes → same handlers).
- **WS4 / Phase 4**: `modelserver/app/classifier.py`, `modelserver/app/schemas.py`, `modelserver/app/main.py` (`/health` fields), `modelserver/MODEL_CARD.md`, offline `training/` (excluded from image), required classical ML + DL/ONNX + LLM zero-shot comparison, `evals/classifier/run.py`.
- **WS5 / Phase 5**: `guardrails/app/rails.py`, `guardrails/app/schemas.py`, reuse `backend/app/services/guardrail_floor.py` + `guardrails/app/platform_floor.yaml`.
- **WS6 / Phase 6**: `evals/redteam_cross_tenant/run.py`, `evals/redaction/run.py`, fixtures — conform to [`001 ci-gate.contract.md`](../001-widget-auth-admin-cicd/contracts/ci-gate.contract.md); root `eval_thresholds.yaml` (canonical Owner C keys). `.github/workflows/ci.yml` wiring is **Owner D** (protected).
- **WS7 / Phase 7**: conditional DL/ONNX serving hardening if selected by the Phase 4 comparison.

## Cross-owner coordination

- **Owner A** — Vault path for `SERVICE_AUTH_TOKEN` (env fallback until ready); `app.tenant_id` context Owner C must not bypass.
- **Owner B** — confirms label consumption; owns the timing of moving callers onto the new endpoint names (WS3 only *adds* them).
- **Owner D** — owns `ci.yml` (gate wiring) and the admin guardrail-config UI.

## Verification

- `cd backend && uv run python -m pytest -q`; same for `modelserver`, `guardrails` (Windows-safe `python -m` form; AppLocker blocks venv `.exe` shims).
- `cd backend && uv run python -m ruff check .` (and per service).
- Eval gates: `python -m evals.common.validate_thresholds`, then each `python -m evals.<gate>.run` printing the contract status line.
- Threshold source: Owner C evals read the root `eval_thresholds.yaml`; `evals/eval_thresholds.yaml` is legacy RAG/router data and not canonical for Owner C gates.
- Lean-serving check: serving lockfiles contain no `torch`/`transformers`.

## Risks

- Dual Owner C spec drift (root SPEC vs this folder) — mitigated by referencing upstream, not restating.
- Protected files (`ci.yml`, `Makefile`, `config.py`, `logging.py`) require coordination/warning before any edit.
- Dataset/served-model choice (WS4) still open, but the comparison candidates are fixed: classical ML, DL/ONNX, and LLM zero-shot.
