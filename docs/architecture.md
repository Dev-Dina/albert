# Architecture

_Placeholder._

Albert is a multi-tenant AI SaaS concierge. The hard part is tenant isolation:
Tenant A must never access Tenant B's data.

Services: backend (FastAPI), admin (Streamlit), modelserver (lean classifier),
guardrails (NeMo Guardrails sidecar + deterministic platform-deny prefilter), plus
postgres (pgvector), redis, minio, and vault.
The authoritative architecture and isolation model live in
[../PROJECT_CONTEXT.md](../PROJECT_CONTEXT.md) and [DESIGN.md](DESIGN.md).
