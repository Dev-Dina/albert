"""Leads page — list this tenant's captured leads (FR-023, US2 scenario 4).

Lists only the caller tenant's leads (the backend derives ``tenant_id`` from the
verified JWT; the client method takes no ``tenant_id`` argument). Default sort is
``created_at DESC`` (backend-ordered); each row shows a status pill, and an empty
tenant renders a designed empty state rather than a blank page.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError, LeadRow
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import status_badge

_STATUS_OPTIONS = ("all", "new", "contacted", "qualified", "won", "lost")

# UI affordance only — the backend lifecycle is authoritative and rejects any
# disallowed transition with 409 (see app.services.lead_lifecycle).
_ALLOWED_NEXT: dict[str, tuple[str, ...]] = {
    "new": ("contacted", "lost"),
    "contacted": ("qualified", "lost"),
    "qualified": ("won", "lost"),
    "won": (),
    "lost": (),
}


def _status_control(client: BackendClient, leads: list[LeadRow]) -> None:
    st.markdown("<h3>Update a lead</h3>", unsafe_allow_html=True)
    labels = {f"{lead.name} — {lead.contact} [{lead.status}]": lead for lead in leads}
    choice = st.selectbox("Select a lead", options=list(labels.keys()))
    lead = labels[choice]
    nexts = _ALLOWED_NEXT.get(lead.status, ())
    if not nexts:
        st.info(f"This lead is in a terminal status ({lead.status}); no further changes.")
        return
    target = st.selectbox("New status", options=nexts, key=f"target-{lead.lead_id}")
    if st.button("Apply status change"):
        try:
            client.update_lead_status(lead.lead_id, status=target)
        except BackendError as exc:
            if handle_backend_error(exc):
                return
            st.error(f"Could not update status: {exc}")
            return
        st.success(f"Lead moved to '{target}'.")
        st.rerun()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Leads</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Visitors captured by your widgets, newest first. '
        "Scoped to your tenant only.</p>",
        unsafe_allow_html=True,
    )

    status_choice = st.selectbox("Filter by status", options=_STATUS_OPTIONS, index=0)
    status_filter = None if status_choice == "all" else status_choice

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)

    try:
        leads = client.list_leads(status=status_filter, limit=200)
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load leads: {exc}", key="leads-retry"):
            st.rerun()
        return

    slot.empty()

    if not leads:
        ui.empty_state(
            "No leads yet",
            description="Leads captured during widget conversations will appear here.",
            icon="📇",
        )
        return

    rows = [
        [
            lead.created_at,
            lead.name,
            lead.contact,
            lead.intent,
            status_badge(lead.status),
        ]
        for lead in leads
    ]
    ui.data_table(
        ["Created", "Name", "Contact", "Intent", "Status"],
        rows,
        raw_cols=(4,),
    )

    _status_control(client, leads)


if __name__ == "__main__":
    main()
