# Albert — Evaluation Overview

How Albert's behaviour is measured and gated. Every gate has a committed threshold
in [`eval_thresholds.yaml`](../eval_thresholds.yaml) (canonical, repo root) and runs in
CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml)); a regression fails the
build. The older `evals/eval_thresholds.yaml` is **legacy** and not canonical.

## Gates at a glance

| Gate | Metric | Threshold | Observed | Source |
|---|---|---|---|---|
| Classifier | macro-F1 (held-out 600) | ≥ 0.95 | **0.9718** | `evals/classifier/` |
| Agent tool-selection | accuracy (15 cases) | ≥ 0.80 | **1.00** | `evals/tool_selection*` |
| RAG — retrieval | hit@5 | ≥ 0.80 | **1.00** | `evals/rag/`, `evals/rag_eval.py` |
| RAG — retrieval | MRR | ≥ 0.50 | **1.00** | same |
| RAG — generation | faithfulness | ≥ 0.80 | **0.974** | same |
| RAG — generation | answer relevancy | ≥ 0.80 | **0.940** | same |
| RAG — judge | hand-label agreement | ≥ 0.80 | **1.00** (14/14) | `evals/rag_judge_labels.jsonl` |
| Red-team (cross-tenant + injection) | pass rate | = 1.00 (floor) | **1.00** | `evals/redteam_cross_tenant/` |
| Redaction (PII / secrets) | pass rate | = 1.00 (floor) | **1.00** (11/0) | `evals/redaction/` |
| Stack smoke | compose up + secured path | pass | **PASS** | `scripts/smoke_test.sh` |

The two safety floors (`redteam`, `redaction`) MUST stay at 1.00 — the first CI step
(`evals/common/validate_thresholds.py`) refuses to run if either is lowered.

## The classifier comparison (ship decision)

Three baselines on the same 600-item held-out split (full detail +
artifact SHA-256s in [`modelserver/MODEL_CARD.md`](../modelserver/MODEL_CARD.md)):

| Baseline | macro-F1 | latency | status |
|---|---|---|---|
| Classical TF-IDF + LogisticRegression | **0.9718** | 0.0101 ms/item | **shipped** |
| DL: sklearn MLP → ONNX | 0.9834 | 0.0419 ms/item | challenger (not served) |
| Gemini zero-shot (`gemini-2.5-flash-lite`) | 0.5036 | 1107 ms/item | rejected |

Highest F1 did not win: the classical model ships for lowest latency, lowest serving
complexity (sklearn+joblib, no torch), and fail-closed SHA-256 verification. Rationale
in [`docs/DECISIONS.md`](DECISIONS.md).

## Routing / cost

The classifier-driven router keeps most turns off the bounded agent. On the committed
15-turn routing set: **80.0% routed off-agent** (drop/rag/lead/escalate), 20.0% reach the
agent. `python -m evals.router_cost` reports the split and an **estimated** dollar saving
(clearly labelled an ESTIMATE — one assumed per-turn cost, not a measured bill).

## How to run

From the repo root (each eval is self-contained):

```bash
# No-DB gates
uv run --project backend  python -m evals.common.validate_thresholds
uv run --project modelserver python -m evals.classifier.run
uv run --project backend  python -m evals.tool_selection_eval --golden evals/tool_selection.jsonl
uv run --project backend  python -m evals.tool_selection.run
uv run --project backend  python -m evals.router_cost
uv run --project guardrails python -m evals.redteam_cross_tenant.run
uv run --project guardrails python -m evals.redaction.run

# RAG (run from repo root; harness scores the committed golden set)
uv run --project backend python -m evals.rag_eval --golden evals/rag_golden.jsonl --labels evals/rag_judge_labels.jsonl
uv run --project backend python -m evals.rag.run

# Isolation (needs a migrated Postgres; see RUNBOOK.md)
cd backend && uv run python -m pytest ../evals/isolation -v

# Full stack smoke (fresh compose stack, seeded secured round-trip)
bash scripts/smoke_test.sh        # SMOKE_SEEDED_CHAT=0 to skip the seeded turn
```

## Honest limitations

- **RAG judge is a frozen, lexical/deterministic rubric — NOT RAGAS and NOT an LLM
  judge.** Faithfulness = generated key terms supported by retrieved chunks; relevancy =
  coverage of ideal-answer key terms. It is CI-safe (no hosted API) and validated against
  a hand-labelled subset (agreement 1.00, 14/14).
- **Cheap-path RAG answers are extractive** (top chunks joined), not LLM-polished.
- **Lead cheap-path** uses conservative contact extraction (`name="Visitor"` when only a
  contact is reliably parseable without an LLM).
- **Cost saved is an estimate** keyed to one assumed per-turn cost, not empirical billing.
- A **legacy duplicate** guardrail-config table (`tenant_guardrail_configs`, migration
  0003) coexists with the live `widget_guardrail_configs` (0004); not yet removed.

## CI wiring

`.github/workflows/ci.yml` runs on every push/PR:
`validate_thresholds` → (lint, typecheck, image_build in parallel) → `smoke` →
five eval gates in parallel (classifier, agent_tool_selection, rag, redteam_cross_tenant,
redaction) → `summary` (always; fails the build if any gate failed). No gate uses
`continue-on-error`, so flakes surface as red.
