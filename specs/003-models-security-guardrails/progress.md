# Owner C Progress Tracker

Central status tracker for Models, Security & Guardrails.

## Phase Status

| Phase | Scope | Status |
|---|---|---|
| Phase 0 | Spec drift fixed | DONE |
| Phase 1 | Service auth verified | PASS |
| Phase 2 | Section C spec coverage | PASS |
| Phase 3 | Endpoint aliases verified | PASS |
| Phase 4A | Public dataset + classical baseline | PASS |
| Phase 4B | Classical model served | PASS |
| Phase 4C | Classifier eval gate runner | PASS |
| Phase 4D | DL/ONNX baseline | PASS |
| Phase 4E | LLM zero-shot baseline | NEXT |
| Phase 5 | Production model decision | PENDING |
| Phase 6 | Guardrails + red-team suite | PENDING |
| Phase 7 | Redaction hardening / credit-card add-on | PENDING |
| Phase 8 | CI handoff | PENDING |

## Key Artifacts

| Artifact | Path / SHA-256 |
|---|---|
| Processed dataset | `training/intent_classifier/data/customer_support_intents_mapped.jsonl` |
| Dataset SHA-256 | `848697bc0d6f6a2a152a89a83dd00e5123dacdcbff86a6a449f84233e2af64ae` |
| Classical joblib artifact | `training/intent_classifier/artifacts/classical_intent_logreg.joblib` |
| Classical artifact SHA-256 | `9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a` |
| DL/ONNX artifact | `training/intent_classifier/artifacts/dl_intent_mlp.onnx` |
| DL/ONNX artifact SHA-256 | `87203e8f3842d420e92a97a8c017124892063285be543c8dc780c898aa3e35b7` |
| Model card | `modelserver/MODEL_CARD.md` |
| Classifier eval runner | `evals/classifier/run.py` |

## Current Metrics

All classifier baselines use the same held-out split:
`training/intent_classifier/artifacts/classical_split.json`.

| Baseline | Macro-F1 | faq_rag F1 | lead_capture F1 | human_escalate F1 | spam F1 | other_agent F1 | Latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| Classical TF-IDF + LogisticRegression | `0.971762` | `0.991597` | `0.954733` | `0.950000` | `0.995816` | `0.966667` | `0.0101 ms/item` |
| DL/ONNX TF-IDF + MLPClassifier | `0.9834` | `0.9958` | `0.9712` | `0.9667` | `0.9958` | `0.9874` | `0.0419 ms/item` |
| LLM zero-shot | Pending | Pending | Pending | Pending | Pending | Pending | Pending |

## Open Risks

- LLM zero-shot baseline is still pending.
- Production choice is not final until the LLM comparison is complete.
- Guardrails still need real rails and red-team suite if not already implemented.
- CI is not wired yet.
- Credit-card redaction is specified but not yet implemented.
- Endpoint migration to target names requires Owner B/D coordination.

## Next Action

Phase 4E: LLM zero-shot baseline on the same held-out split.
