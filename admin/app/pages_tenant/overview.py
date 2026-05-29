"""Tenant overview — bento landing for tenant_admin (FR-041).

Four cards (``data-model.md`` ``OverviewMetrics``): leads in the last 30 days ·
active widgets · guardrails status · signing-key state. The leads-last-30d card
uses a single ``list_leads(since=30d, limit=200)`` call and shows "200+" when
the response is full. Renders loading / error states.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session

_LEADS_PAGE = 200


def _iso_30d_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown(
        "<h1>Overview</h1>"
        '<p class="albert-meta">Your tenant at a glance — leads, widgets, '
        "guardrails, and signing-key state.</p>",
        unsafe_allow_html=True,
    )

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)

    try:
        leads = client.list_leads(since=_iso_30d_ago(), limit=_LEADS_PAGE)
        widgets = client.list_widgets()
        guardrails = client.get_guardrail_config()
        signing_key = client.get_signing_key()
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Couldn't load the overview: {exc}", key="t-ov-retry"):
            st.rerun()
        return

    slot.empty()

    leads_label = f"{_LEADS_PAGE}+" if len(leads) >= _LEADS_PAGE else str(len(leads))
    active_widgets = sum(1 for w in widgets if w.status == "enabled")
    guardrails_ok = bool(guardrails)
    signing_key_state = "active" if signing_key is not None else "none"

    ui.bento_grid(
        [
            {
                "label": "Leads (30 days)",
                "value": leads_label,
                "secondary": "captured in the last 30 days",
            },
            {
                "label": "Active widgets",
                "value": active_widgets,
                "secondary": f"of {len(widgets)} total",
            },
            {
                "label": "Guardrails",
                "value": "Configured" if guardrails_ok else "Not set",
                "secondary": "tenant guardrail config",
            },
            {
                "label": "Signing key",
                "value": signing_key_state,
                "secondary": "widget token signing state",
            },
        ]
    )


if __name__ == "__main__":
    main()
