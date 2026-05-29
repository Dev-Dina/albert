"""Platform overview — bento landing for tenant_manager (FR-041).

Four cards: total tenants · active vs suspended · 30-day platform cost · a
sample of the 5 most-recent audit events. Renders loading / empty / error
states. No tenant content is fetched here (lifecycle + aggregates only).
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
        "<h1>Platform overview</h1>"
        '<p class="albert-meta">Fleet lifecycle and aggregate cost. '
        "No tenant content is shown on the platform surface.</p>",
        unsafe_allow_html=True,
    )

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)

    try:
        tenants = client.list_tenants(limit=200)
        costs = client.get_cost_all(since=_iso_30d_ago())
        recent = client.list_audit(limit=5)
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Couldn't load the overview: {exc}", key="ov-retry"):
            st.rerun()
        return

    slot.empty()

    total = len(tenants)
    active = sum(1 for t in tenants if t.status == "active")
    suspended = sum(1 for t in tenants if t.status == "suspended")
    platform_cost = sum((Decimal(c.total_cost_usd) for c in costs), Decimal("0"))

    ui.bento_grid(
        [
            {"label": "Total tenants", "value": total},
            {
                "label": "Active / suspended",
                "value": f"{active} / {suspended}",
                "secondary": "active vs suspended tenants",
            },
            {
                "label": "30-day platform cost",
                "value": f"${platform_cost:.2f}",
                "secondary": "sum across all tenants",
            },
            {
                "label": "Recent activity",
                "value": len(recent),
                "secondary": "most-recent audit events",
            },
        ]
    )

    st.markdown("<h2>Recent activity</h2>", unsafe_allow_html=True)
    if not recent:
        ui.empty_state(
            "No activity yet",
            description="Lifecycle actions across all tenants will appear here.",
        )
    else:
        ui.timeline(
            [
                {
                    "title": entry.action,
                    "meta": " · ".join(
                        part
                        for part in (
                            entry.actor_email,
                            entry.target_tenant_slug,
                            entry.created_at,
                        )
                        if part
                    ),
                }
                for entry in recent
            ]
        )


if __name__ == "__main__":
    main()
