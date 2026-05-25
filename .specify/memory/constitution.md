<!--
SYNC IMPACT REPORT
Version change: (unversioned template) → 1.0.0
Bump rationale: Initial ratification — placeholders replaced with concrete, project-specific principles.

Principles defined (all new this version):
- I. Tenant Isolation Is Absolute (NON-NEGOTIABLE)
- II. Layered Architecture & Async Discipline
- III. Security & Secrets Hygiene (NON-NEGOTIABLE)
- IV. Test Integrity for Changed Behavior
- V. Spec-Driven, Phased Delivery

Added sections:
- Security & Operational Constraints
- Development Workflow & Quality Gates

Removed sections: none

Templates / artifacts reviewed:
- .specify/templates/plan-template.md ......... ✅ aligned (generic Constitution Check gate references this file; no edit needed)
- .specify/templates/spec-template.md ......... ✅ aligned (no principle-specific assumptions)
- .specify/templates/tasks-template.md ........ ✅ aligned (tests OPTIONAL flag coexists with Principle IV, which scopes to *changed behavior*)
- .specify/templates/commands/*.md ............ ✅ no agent-specific references requiring change

Follow-up TODOs: none
Source of derived values: CLAUDE.md (project rules) — user input was empty.
-->

# Albert Constitution

## Core Principles

### I. Tenant Isolation Is Absolute (NON-NEGOTIABLE)

Albert is multi-tenant. Cross-tenant access is the one failure the project cannot tolerate.

- Tenant A MUST NEVER access Tenant B's data, vectors, leads, conversations, prompts,
  widget config, costs, or sessions.
- Tenant identity MUST be derived from verified auth/session/widget token. It MUST NOT be
  read from a visitor or client request body.
- Every tenant-owned database row MUST be scoped by tenant.
- RAG/vector retrieval MUST filter by tenant.
- Platform guardrails MUST NOT be weakenable by tenant configuration.

**Rationale**: A single cross-tenant leak destroys customer trust irreversibly and may breach
contractual and legal obligations. This principle outranks every other concern, including
velocity and convenience, and cannot be waived.

### II. Layered Architecture & Async Discipline

- Logic MUST be separated across these layers: routes, schemas, services, repositories,
  clients, config.
- API, database, and network work MUST use async patterns.
- Configuration MUST be centralized; scattered or hardcoded configuration is prohibited.
- Observability MUST use logging, never `print`.

**Rationale**: Clear layer boundaries make tenant scoping and guardrail enforcement auditable
in one place rather than scattered across call sites. Async I/O keeps the multi-tenant
serving path responsive under concurrent load.

### III. Security & Secrets Hygiene (NON-NEGOTIABLE)

- Secrets MUST NOT be hardcoded.
- `.env` MUST NOT be committed.
- Real API keys, tokens, passwords, or private keys MUST NOT be added to the repository.
- Secrets, tokens, passwords, and raw sensitive data MUST NOT be logged.

**Rationale**: Leaked credentials compromise every tenant at once, collapsing tenant isolation
from the outside. Secret hygiene is therefore a precondition of Principle I.

### IV. Test Integrity for Changed Behavior

- Tests MUST NOT be skipped for changed behavior.
- Any change to behavior MUST be covered by a test before that change is considered done.

**Rationale**: Tenant-isolation and guardrail regressions are catastrophic and usually silent.
Tests on changed behavior are the tripwire that catches them before release.

### V. Spec-Driven, Phased Delivery

- Feature work MUST use the Spec Kit workflow.
- Risky features MUST run the full flow: specify → clarify → plan → tasks → analyze → implement.
  Risky features include auth, tenant isolation, RLS, widget token auth, service-to-service
  auth, guardrails, erasure, and CI eval gates.
- Work MUST NOT build ahead of the requested phase.
- PRs MUST be small and focused.
- Direct pushes to `main` are prohibited; all work happens on a branch.

**Rationale**: Phased, reviewed delivery limits blast radius and keeps every change auditable —
essential when the change surface includes tenant boundaries and platform guardrails.

## Security & Operational Constraints

- Docker containers MUST stay lean.
- `torch` or `transformers` MUST NOT be added to serving containers without explicit approval.
- The following files are PROTECTED. A contributor (human or agent) MUST warn before editing
  them and MUST NOT edit them silently:
  - `.env.example`, `.gitignore`, `.dockerignore`, `docker-compose.yml`, `Makefile`
  - `.github/workflows/*`
  - `backend/app/core/config.py`, `backend/app/core/security.py`, `backend/app/core/logging.py`
  - `backend/app/db/session.py`
  - auth files, tenant isolation files, database migrations, platform prompts

## Development Workflow & Quality Gates

- Spec Kit is the entry point for feature work; the simple flow (specify → plan → tasks →
  implement) applies only to features that are not risky per Principle V.
- Code review MUST verify: tenant scoping of new data access (Principle I), secret hygiene
  (Principle III), and test coverage for changed behavior (Principle IV).
- Git actions MUST NOT be run automatically by tooling or agents unless the user explicitly
  asks; prefer suggesting commands over executing them.

## Governance

- This constitution supersedes other practices. Where another document conflicts with it, this
  constitution wins.
- Amendments MUST be documented, reviewed, and accompanied by a version bump in this file.
- Versioning policy (semantic):
  - **MAJOR**: backward-incompatible governance/principle removal or redefinition.
  - **MINOR**: a new principle/section is added, or guidance is materially expanded.
  - **PATCH**: clarifications, wording, and non-semantic refinements.
- Compliance: every PR and review MUST verify compliance with these principles. Added
  complexity MUST be justified against a simpler rejected alternative.
- Principle I (Tenant Isolation) is non-negotiable and MUST NOT be waived by any amendment that
  weakens it without a MAJOR version bump and explicit, documented approval.

**Version**: 1.0.0 | **Ratified**: 2026-05-25 | **Last Amended**: 2026-05-25
