"""Schema for the cross-tenant daily cost-series endpoint (FR-050 exception 4).

Backs the Cost Overview per-row sparkline (FR-015) in one batched call. The
field set here is the content-exclusion allowlist for
``GET /tenants/cost/series``: numeric cost/token buckets only — no tenant
content. ``test_tenants_cost_series.py`` asserts the response JSON keys stay
within ``{tenant_id, buckets, date, cost_usd, total_tokens}``.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel


class CostBucket(BaseModel):
    date: str  # YYYY-MM-DD
    cost_usd: str  # stringified Decimal, mirroring the existing cost endpoints
    total_tokens: int


class CostSeriesResponse(BaseModel):
    tenant_id: UUID
    buckets: list[CostBucket]
