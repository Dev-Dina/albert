"""Per-tenant cost attribution.

Records every LLM and embedding call as a ``cost_events`` row tagged with the
tenant that triggered it.  Exposes an aggregate read for the tenant_manager
(counts + totals, never per-row content).

Tagging interface for B and C:
  await record_cost_event(db=db, tenant_id=tid, call_type="llm", model="...", ...)

The tenant_manager read path (aggregate_cost_for_tenant) returns only numeric
summaries — no conversations, no message content.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.cost_event import CostEvent

logger = logging.getLogger(__name__)


async def record_cost_event(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    call_type: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: Decimal = Decimal("0"),
    conversation_id: uuid.UUID | None = None,
) -> CostEvent:
    """Insert a cost_events row for a single LLM or embedding call.

    tenant_id is taken from the verified request context (passed in by the
    calling service), never from client input.

    call_type is one of: "llm", "embedding".
    """
    event = CostEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        call_type=call_type,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
    )
    db.add(event)
    await db.flush()
    return event


async def aggregate_cost_for_tenant(
    *,
    db: AsyncSession,
    tenant_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Return aggregate token and cost totals for a tenant.

    Returns counts and sums only — never per-row content.
    Accessible by tenant_manager only (enforced at the route layer).

    Example response shape::

        {
            "tenant_id": "...",
            "total_events": 142,
            "total_input_tokens": 84000,
            "total_output_tokens": 12000,
            "total_cost_usd": "1.234560",
        }
    """
    q = select(
        func.count(CostEvent.id).label("total_events"),
        func.coalesce(func.sum(CostEvent.input_tokens), 0).label("total_input_tokens"),
        func.coalesce(func.sum(CostEvent.output_tokens), 0).label("total_output_tokens"),
        func.coalesce(func.sum(CostEvent.cost_usd), Decimal("0")).label("total_cost_usd"),
    ).where(CostEvent.tenant_id == tenant_id)

    if since is not None:
        q = q.where(CostEvent.created_at >= since)
    if until is not None:
        q = q.where(CostEvent.created_at <= until)

    result = await db.execute(q)
    row = result.one()
    return {
        "tenant_id": str(tenant_id),
        "total_events": row.total_events,
        "total_input_tokens": row.total_input_tokens,
        "total_output_tokens": row.total_output_tokens,
        "total_cost_usd": str(row.total_cost_usd),
    }


async def aggregate_cost_all_tenants(
    *,
    db: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return per-tenant aggregate cost totals (manager dashboard).

    Returns one row per tenant with numeric summaries only.
    Accessible by tenant_manager only (enforced at the route layer).
    """
    q = select(
        CostEvent.tenant_id,
        func.count(CostEvent.id).label("total_events"),
        func.coalesce(func.sum(CostEvent.input_tokens), 0).label("total_input_tokens"),
        func.coalesce(func.sum(CostEvent.output_tokens), 0).label("total_output_tokens"),
        func.coalesce(func.sum(CostEvent.cost_usd), Decimal("0")).label("total_cost_usd"),
    ).group_by(CostEvent.tenant_id)

    if since is not None:
        q = q.where(CostEvent.created_at >= since)
    if until is not None:
        q = q.where(CostEvent.created_at <= until)

    result = await db.execute(q)
    return [
        {
            "tenant_id": str(row.tenant_id),
            "total_events": row.total_events,
            "total_input_tokens": row.total_input_tokens,
            "total_output_tokens": row.total_output_tokens,
            "total_cost_usd": str(row.total_cost_usd),
        }
        for row in result.all()
    ]


async def aggregate_cost_series_all_tenants(
    *,
    db: AsyncSession,
    since: datetime | None = None,
    until: datetime | None = None,
    granularity: str = "daily",
) -> list[dict[str, Any]]:
    """Return a zero-filled daily cost/token series per tenant (FR-050 exc. 4).

    Backs the Cost Overview sparkline (FR-015) in ONE batched call — no per-row
    fan-out. Numeric only (cost + token sums per day); never per-row content.
    Accessible by tenant_manager only (enforced at the route layer).

    The window defaults to the last 30 days (``until`` = now, ``since`` =
    29 days before ``until``, inclusive → 30 daily buckets). Days with no
    events are zero-filled so every tenant renders an equal-length sparkline.

    Grouping is done in Python (not ``date_trunc``) so the same code path runs
    on the SQLite unit-test engine and on production Postgres. The window is
    still a single SELECT, so there is one round trip per call.
    """
    if granularity != "daily":  # v1 supports daily only.
        granularity = "daily"
    until = until or datetime.now(timezone.utc)
    since = since or (until - timedelta(days=29))

    q = select(
        CostEvent.tenant_id,
        CostEvent.created_at,
        CostEvent.cost_usd,
        CostEvent.input_tokens,
        CostEvent.output_tokens,
    ).where(CostEvent.created_at >= since, CostEvent.created_at <= until)

    result = await db.execute(q)
    rows = result.all()

    # Inclusive daily axis from since..until.
    axis: list[Any] = []
    day = since.date()
    last_day = until.date()
    while day <= last_day:
        axis.append(day)
        day = day + timedelta(days=1)

    # tenant_id -> {date -> [cost_usd, total_tokens]}
    per_tenant: dict[Any, dict[Any, list[Any]]] = {}
    for row in rows:
        bucket = per_tenant.setdefault(row.tenant_id, {})
        agg = bucket.setdefault(row.created_at.date(), [Decimal("0"), 0])
        agg[0] += row.cost_usd
        agg[1] += int(row.input_tokens) + int(row.output_tokens)

    series: list[dict[str, Any]] = []
    for tenant_id, bucket in per_tenant.items():
        buckets = [
            {
                "date": axis_day.isoformat(),
                "cost_usd": str(bucket.get(axis_day, [Decimal("0"), 0])[0]),
                "total_tokens": bucket.get(axis_day, [Decimal("0"), 0])[1],
            }
            for axis_day in axis
        ]
        series.append({"tenant_id": str(tenant_id), "buckets": buckets})
    return series
