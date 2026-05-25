# Feature Specification: Service Health Shells

**Feature Branch**: `002-service-health-shells`

**Created**: 2026-05-25

**Status**: Draft

**Input**: User description: "Build minimal runnable service shells for Albert — backend, modelserver, and guardrails — each a FastAPI app with a health endpoint plus placeholder endpoints, with minimal tests. No Docker, auth, database, RAG, agent, tenant isolation, real classifier, or real guardrails."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Backend service responds to health checks (Priority: P1)

A platform operator (or monitoring/CI system) calls the backend service's health
endpoint to confirm the service is running and correctly identifies itself.

**Why this priority**: The backend is the central service. A runnable, health-reporting
backend is the smallest slice that proves the foundation works and unblocks every later
phase. On its own it is a viable, demonstrable MVP.

**Independent Test**: Start only the backend service, call its health endpoint, and confirm
it returns the documented status/service/app payload.

**Acceptance Scenarios**:

1. **Given** the backend service is running, **When** a caller requests the health endpoint,
   **Then** the response reports status `ok`, service `backend`, and app `albert`.
2. **Given** the backend service is running, **When** the health endpoint is called repeatedly,
   **Then** every response is identical and successful.

---

### User Story 2 - Modelserver health and prediction placeholder (Priority: P2)

A caller confirms the modelserver is running via its health endpoint, and can call a
prediction placeholder that returns a fixed, well-formed response (no real model yet).

**Why this priority**: The modelserver is a distinct deployable. Its health check plus a
stable prediction contract lets downstream work integrate against a known shape before any
real classifier exists.

**Independent Test**: Start only the modelserver, call its health endpoint and its prediction
endpoint, and confirm both return the documented payloads.

**Acceptance Scenarios**:

1. **Given** the modelserver is running, **When** a caller requests the health endpoint,
   **Then** the response reports status `ok`, service `modelserver`, and app `albert`.
2. **Given** the modelserver is running, **When** a caller posts to the prediction endpoint,
   **Then** the response reports label `unknown` and confidence `0.0`.

---

### User Story 3 - Guardrails health and input/output check placeholders (Priority: P3)

A caller confirms the guardrails service is running via its health endpoint, and can call
input-check and output-check placeholders that return fixed "allowed" responses (no real
guardrail logic yet).

**Why this priority**: Guardrails is a distinct deployable that later enforces platform
safety. A stable placeholder contract lets downstream work wire in the check calls before
real enforcement exists. It is lowest priority because nothing depends on it for this phase.

**Independent Test**: Start only the guardrails service, call its health, input-check, and
output-check endpoints, and confirm all three return the documented payloads.

**Acceptance Scenarios**:

1. **Given** the guardrails service is running, **When** a caller requests the health endpoint,
   **Then** the response reports status `ok`, service `guardrails`, and app `albert`.
2. **Given** the guardrails service is running, **When** a caller posts to the input-check
   endpoint, **Then** the response reports allowed `true` and reason `phase_1_placeholder`.
3. **Given** the guardrails service is running, **When** a caller posts to the output-check
   endpoint, **Then** the response reports allowed `true` and reason `phase_1_placeholder`.

---

### Edge Cases

- Requests to placeholder endpoints with an empty or unexpected body still return the fixed
  documented response (the body is ignored in this phase).
- Each service runs and is testable independently of the other two; none requires another
  service to be up.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The backend service MUST expose a health endpoint at `GET /health` returning a
  JSON object with `status` = `ok`, `service` = `backend`, `app` = `albert`.
- **FR-002**: The modelserver service MUST expose a health endpoint at `GET /health` returning
  a JSON object with `status` = `ok`, `service` = `modelserver`, `app` = `albert`.
- **FR-003**: The modelserver service MUST expose a placeholder prediction endpoint at
  `POST /predict` returning a JSON object with `label` = `unknown` and `confidence` = `0.0`.
- **FR-004**: The guardrails service MUST expose a health endpoint at `GET /health` returning a
  JSON object with `status` = `ok`, `service` = `guardrails`, `app` = `albert`.
- **FR-005**: The guardrails service MUST expose a placeholder input-check endpoint at
  `POST /check-input` returning a JSON object with `allowed` = `true` and
  `reason` = `phase_1_placeholder`.
- **FR-006**: The guardrails service MUST expose a placeholder output-check endpoint at
  `POST /check-output` returning a JSON object with `allowed` = `true` and
  `reason` = `phase_1_placeholder`.
- **FR-007**: Each of the three services MUST be runnable independently, without requiring the
  other services, a database, external secrets, or any container tooling.
- **FR-008**: Each service MUST have at least one automated test that verifies every endpoint
  it exposes returns the documented response.
- **FR-009**: All endpoint responses MUST be JSON containing exactly the documented fields and
  values for this phase.

### Key Entities

- **Health response**: A fixed status object identifying the service. Fields: `status`,
  `service`, `app`.
- **Prediction response (placeholder)**: A fixed classification result. Fields: `label`,
  `confidence`.
- **Guardrail check response (placeholder)**: A fixed allow/deny decision with a reason.
  Fields: `allowed`, `reason`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All three services can each be started independently and each returns a
  successful health response identifying itself correctly.
- **SC-002**: 100% of defined endpoints return exactly the documented fields and values.
- **SC-003**: Each service has automated tests covering every endpoint it exposes, and those
  tests pass.
- **SC-004**: A developer can start any single service and confirm its health endpoint in under
  2 minutes from a clean checkout.
- **SC-005**: A health check returns a response in under 500 ms under local, idle conditions.

## Out of Scope

The following are explicitly excluded from this feature and deferred to later phases:

- Dockerfiles and Docker Compose service definitions
- Authentication and authorization
- Database access or models
- Secrets management (e.g., Vault) logic
- Redis logic
- Object storage (e.g., MinIO) logic
- RAG / vector retrieval
- The AI agent
- Tenant isolation
- The embeddable widget
- Streamlit / admin UI
- Any real classifier (prediction returns a fixed placeholder)
- Any real guardrail logic (checks always allow with a placeholder reason)

## Assumptions

- Each service is a standalone FastAPI application, consistent with Albert's documented stack
  and existing folder skeleton (`backend/`, `modelserver/`, `guardrails/`).
- All endpoints respond with HTTP 200 on success in this phase.
- Placeholder POST endpoints accept any (or empty) request body and ignore its contents; no
  request schema is enforced yet.
- Services run on separate ports/processes when run together, but no service-to-service calls
  are required.
- "Minimal tests" means automated endpoint tests using the project's standard test runner,
  scoped to the endpoints defined here.
- This feature is not a "risky feature" per the project constitution (no auth, tenant
  isolation, or real guardrail logic), so the simple Spec Kit flow applies.
