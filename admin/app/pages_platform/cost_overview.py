"""Cost Overview — sortable per-tenant table with 30-day sparklines (FR-015).

The daily series for every row comes from a SINGLE ``get_cost_series`` call
keyed by ``tenant_id`` (no per-row fan-out). As a consistency guard, the sum
of per-row scalar totals (``/cost/all``) is compared against the sum of the
batched daily series; on divergence the page renders an error state instead of
a misleading table (data-model.md validation).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session


def _iso_30d_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)
    st.markdown(
        "<h1>Cost overview</h1>"
        '<p class="albert-meta">Per-tenant token cost over the last 30 days. '
        "Daily sparklines are fetched in one batched call.</p>",
        unsafe_allow_html=True,
    )

    since = _iso_30d_ago()
    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(5)

    try:
        tenants = client.list_tenants(limit=200)
        costs = client.get_cost_all(since=since)
        series = client.get_cost_series(since=since)
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Couldn't load cost data: {exc}", key="co-retry"):
            st.rerun()
        return

    slot.empty()

    if not costs:
        ui.empty_state(
            "No cost data yet",
            description="Cost appears once tenants start using the assistant.",
        )
        return

    # Consistency guard: per-row scalar totals must agree with the batched
    # daily series (mirrors the backend contract test).
    scalar_total = sum((Decimal(c.total_cost_usd) for c in costs), Decimal("0"))
    series_total = sum(
        (Decimal(point.cost_usd) for points in series.values() for point in points),
        Decimal("0"),
    )
    if scalar_total != series_total:
        ui.error_state(
            "Cost totals are inconsistent between the summary and the daily "
            f"series (${scalar_total} vs ${series_total}). Refusing to render a "
            "misleading table.",
            key="co-mismatch",
        )
        return

    name_by_id = {t.tenant_id: t for t in tenants}

    sort_label = st.selectbox(
        "Sort by",
        ["Cost (high → low)", "Cost (low → high)", "Tokens (high → low)"],
    )

    def _tokens(cost) -> int:
        return cost.total_input_tokens + cost.total_output_tokens

    if sort_label == "Cost (low → high)":
        costs_sorted = sorted(costs, key=lambda c: Decimal(c.total_cost_usd))
    elif sort_label == "Tokens (high → low)":
        costs_sorted = sorted(costs, key=_tokens, reverse=True)
    else:
        costs_sorted = sorted(costs, key=lambda c: Decimal(c.total_cost_usd), reverse=True)

    st.markdown(
        f'<div class="albert-card-label">Platform total (30d)</div>'
        f'<div class="albert-card-metric">${scalar_total:.2f}</div>',
        unsafe_allow_html=True,
    )

    rows = []
    for cost in costs_sorted:
        tenant = name_by_id.get(cost.tenant_id)
        samples = [float(point.cost_usd) for point in series.get(cost.tenant_id, [])]
        rows.append(
            [
                tenant.name if tenant else cost.tenant_id,
                tenant.slug if tenant else "—",
                f"${Decimal(cost.total_cost_usd):.2f}",
                f"{_tokens(cost):,}",
                ui.sparkline(samples) if samples else '<span class="albert-muted">—</span>',
            ]
        )
    ui.data_table(
        ["Tenant", "Slug", "Cost (30d)", "Tokens", "Daily trend"],
        rows,
        raw_cols=(4,),
    )


if __name__ == "__main__":
    main()
