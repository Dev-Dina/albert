"""Tenant Detail — lifecycle metadata + aggregate cost (FR-014).

Shows the selected tenant's lifecycle metadata and an aggregate cost block.
An ``erased`` / ``suspended`` tenant renders an explicit state badge (not a
404-style empty page). MUST NOT fetch or show conversations, messages, leads,
CMS, or vectors — lifecycle + numeric aggregates only.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session


def _iso_30d_ago() -> str:
    return (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()


def _status_class(status: str) -> str:
    return {
        "active": "albert-badge-success",
        "suspended": "albert-badge-warning",
        "erased": "albert-badge-danger",
    }.get(status, "albert-badge-muted")


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)
    st.markdown("<h1>Tenant detail</h1>", unsafe_allow_html=True)

    try:
        tenants = client.list_tenants(limit=200)
    except BackendError as exc:
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Couldn't load tenants: {exc}", key="td-list-retry"):
            st.rerun()
        return

    if not tenants:
        ui.empty_state("No tenants yet", description="Create a tenant first.")
        return

    by_label = {f"{t.name} ({t.slug})": t for t in tenants}
    choice = st.selectbox("Select a tenant", list(by_label.keys()))
    selected = by_label[choice]

    try:
        tenant = client.get_tenant(selected.tenant_id)
        cost = client.get_tenant_cost(selected.tenant_id, since=_iso_30d_ago())
    except BackendError as exc:
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Couldn't load tenant detail: {exc}", key="td-retry"):
            st.rerun()
        return

    st.markdown(
        f'<h2>{tenant.name} '
        f'<span class="albert-badge {_status_class(tenant.status)}">{tenant.status}</span>'
        "</h2>",
        unsafe_allow_html=True,
    )

    if tenant.status == "erased":
        st.warning(
            f"This tenant was erased (as of {(tenant.updated_at or '')[:10]}). "
            "Lifecycle metadata is shown for the record; no content exists."
        )
    elif tenant.status == "suspended":
        st.warning(
            f"This tenant is suspended (as of {(tenant.updated_at or '')[:10]}). "
            "Reactivate it from the Tenants page to restore access."
        )

    ui.bento_grid(
        [
            {"label": "Slug", "value": tenant.slug},
            {"label": "Status", "value": tenant.status},
            {"label": "Created", "value": (tenant.created_at or "")[:10]},
            {"label": "Updated", "value": (tenant.updated_at or "")[:10]},
        ]
    )

    st.markdown("<h2>Aggregate cost (last 30 days)</h2>", unsafe_allow_html=True)
    ui.bento_grid(
        [
            {"label": "Total cost", "value": f"${float(cost.total_cost_usd):.2f}"},
            {"label": "Events", "value": cost.total_events},
            {"label": "Input tokens", "value": f"{cost.total_input_tokens:,}"},
            {"label": "Output tokens", "value": f"{cost.total_output_tokens:,}"},
        ]
    )


if __name__ == "__main__":
    main()
