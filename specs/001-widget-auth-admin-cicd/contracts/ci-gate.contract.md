# Contract: CI Pipeline and Eval Gates

## Pipeline order (FR-021)

GitHub Actions workflow `.github/workflows/ci.yml`, triggered on `push` (any
branch) and `pull_request`:

1. **Lint** — `ruff check` over `backend/`, `admin/`, `modelserver/`,
   `guardrails/`, `evals/`. Parallel with #2 and #3.
2. **Type-check** — `mypy` or `pyright` over the same set. Parallel.
3. **Image build** — `docker compose build` (cached layers). Parallel.
4. **Smoke** — depends on #3. `scripts/smoke_test.sh` runs `docker compose up -d`,
   waits for `/health` on backend (8000), modelserver (8020), guardrails (8010),
   asserts each returns 200. Failure here **short-circuits the eval gates**
   (FR-028).
5. **Eval gates** — depend on #4. Run **in parallel** as four jobs:
   - `classifier` (FR-023) — `evals/classifier/run.py`; gate on `classifier.macro_f1_min`.
   - `agent_tool_selection` (FR-024) — gate on `agent_tool_selection.accuracy_min`.
   - `rag` (FR-025) — gate on `rag.hit_at_5_min` AND `rag.mrr_min`.
   - `redteam_cross_tenant` (FR-026) — gate on `redteam.required_pass_rate` (must be 1.00).
   - `redaction` (FR-027) — gate on `redaction.required_pass_rate` (must be 1.00).

(Note: "four eval gates" in the spec = classifier + tool_selection + rag +
redteam. Redaction is the fifth gate called out separately in FR-027 and runs
in parallel with the four.)

## Gate runner contract

Each `evals/<gate>/run.py` MUST:
- Accept no positional args; read fixtures and thresholds itself.
- Load thresholds via `evals/common/thresholds.py` which parses
  `eval_thresholds.yaml`.
- Print a single final line in the format:
  ```
  GATE=<name> STATUS=<pass|fail|error> OBSERVED=<value-or-NA> THRESHOLD=<value-or-NA>
  ```
- Exit `0` on pass, `1` on fail, `2` on error (harness crash).
- Append a JSON record to `$GITHUB_STEP_SUMMARY`-compatible artifact
  `artifacts/ci-gate-results.json` (jsonl) so a downstream summary step can
  print all gates in the PR check view (FR-029).

## Failure reporting (FR-029)

A final job `summary` runs `always()` after all gates, reads the jsonl
artifact, and writes a Markdown table to `$GITHUB_STEP_SUMMARY` of the form:

| gate | status | observed | threshold |
|---|---|---|---|
| classifier | fail | 0.55 | 0.60 |
| ... | ... | ... | ... |

The PR check title MUST include the first failed gate name (e.g.
"CI / classifier failed (0.55 < 0.60)").

## No silent retries (FR-030)

- Steps MUST NOT use `continue-on-error: true` for any gate.
- Steps MUST NOT use `if: failure()` to retry the same step.
- A flake MUST surface as a red check the same way a real regression does.
- If a contributor needs to re-run, they re-run the workflow from the UI —
  CI itself never papers over.

## Threshold file (FR-022)

`eval_thresholds.yaml` lives at the repo root (already in place). Schema:

```yaml
classifier:
  macro_f1_min: <float 0..1>
agent_tool_selection:
  accuracy_min: <float 0..1>
rag:
  hit_at_5_min: <float 0..1>
  mrr_min: <float 0..1>
redteam:
  required_pass_rate: 1.00      # MUST be exactly 1.00 (FR-026)
redaction:
  required_pass_rate: 1.00      # MUST be exactly 1.00 (FR-027)
smoke:
  required_pass_rate: 1.00
```

Any PR that lowers `redteam.required_pass_rate` or `redaction.required_pass_rate`
below 1.00 MUST be rejected in review per Constitution Principle I and III.
A lint-style validator (`evals/common/validate_thresholds.py`) runs first in
the pipeline to enforce this invariant.
