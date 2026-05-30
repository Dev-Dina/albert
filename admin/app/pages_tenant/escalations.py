"""Escalations page — review conversations handed off to a human (feature 007, US3).

Lists this tenant's escalated conversations with their captured reason and
summary so a human can follow up with full context. Read-only in v1. The backend
derives ``tenant_id`` from the verified JWT (the client takes no ``tenant_id``);
an empty tenant renders a designed empty state.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError, EscalationRow
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session

# UI affordance only — the backend lifecycle is authoritative. ``all`` maps to no
# status filter; the view defaults to ``open`` (FR-009).
_STATUS_OPTIONS = ("open", "resolved", "all")


def _set_status(client: BackendClient, conversation_id: str, status: str) -> None:
    try:
        client.set_escalation_status(conversation_id, status=status)
    except BackendError as exc:
        if handle_backend_error(exc):
            return
        st.error(f"Could not update escalation: {exc}")
        return
    st.rerun()


def _render(client: BackendClient, esc: EscalationRow) -> None:
    label = "✅ resolved" if esc.status == "resolved" else "🔴 open"
    with st.expander(f"[{label}]  {esc.reason[:70]}  —  {esc.updated_at}"):
        st.markdown(f"**Conversation:** `{esc.conversation_id}`")
        st.markdown(f"**Conversation status:** {esc.conversation_status}")
        st.markdown(f"**Escalation status:** {esc.status}")
        if esc.status == "resolved":
            st.caption(f"Resolved by {esc.resolved_by or '—'} at {esc.resolved_at or '—'}")
        st.markdown("**Reason**")
        st.write(esc.reason)
        st.markdown("**Summary**")
        st.write(esc.summary or "_(none provided)_")

        if esc.status == "open":
            if st.button("Resolve", key=f"resolve-{esc.conversation_id}", type="primary"):
                _set_status(client, esc.conversation_id, "resolved")
        else:
            if st.button("Reopen", key=f"reopen-{esc.conversation_id}"):
                _set_status(client, esc.conversation_id, "open")


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Escalations</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Conversations your agent handed off to a human, '
        "newest first. Scoped to your tenant only.</p>",
        unsafe_allow_html=True,
    )

    status_choice = st.selectbox("Filter by status", options=_STATUS_OPTIONS, index=0)
    status_filter = None if status_choice == "all" else status_choice

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)
    try:
        escalations = client.list_escalations(status=status_filter, limit=200)
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load escalations: {exc}", key="esc-retry"):
            st.rerun()
        return
    slot.empty()

    if not escalations:
        ui.empty_state(
            "No escalations here",
            description="When the agent hands a conversation to a human, it will "
            "appear here with the reason and context. Resolved items move out of the "
            "default view.",
            icon="🚩",
        )
        return

    for esc in escalations:
        _render(client, esc)


if __name__ == "__main__":
    main()
