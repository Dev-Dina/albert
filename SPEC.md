# Albert — Specifications Index

Albert was built spec-first (Spec-Driven Development). This file indexes the component
specs; each was written before its code. The cross-cutting contracts (tenant model, role
model, agent tool contracts) are the isolation- and behaviour-defining specs.

## Cross-cutting contracts

- [Tenant model](specs/tenant_model.md) — the `tenant_id` convention and isolation rules.
- [Role model](specs/role_model.md) — three roles, two levels; Tenant-Manager doorway.
- [Agent tool contracts](specs/agent_tool_contracts.md) — `rag_search`, `capture_lead`, `escalate`.
- [Models / security / guardrails spec](specs/models_security_guardrails_SPEC.md).

## Feature specs

- [Widget auth, admin & CI/CD](specs/001-widget-auth-admin-cicd/spec.md)
- [Agent, LLM & tools](specs/001-agent-llm-tools/spec.md)
- [Tenant admin & management](specs/001-tenant-admin-mgmt/spec.md)
- [RAG pipeline](specs/002-rag-pipeline/spec.md)
- [Memory & router](specs/003-memory-router/spec.md)
- [Models, security & guardrails](specs/003-models-security-guardrails/spec.md)

## Related docs

- Architecture & isolation: [docs/DESIGN.md](docs/DESIGN.md), [PROJECT_CONTEXT.md](PROJECT_CONTEXT.md)
- Decisions (ADRs): [docs/DECISIONS.md](docs/DECISIONS.md)
- Evaluation: [docs/EVALS.md](docs/EVALS.md) · Operations: [docs/RUNBOOK.md](docs/RUNBOOK.md)
- Secrets: [docs/SECRETS.md](docs/SECRETS.md) · Security: [SECURITY.md](SECURITY.md)
