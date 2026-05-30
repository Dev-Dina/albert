"""Escalations page — review conversations handed off to a human (feature 007, US3).

Lists this tenant's escalated conversations with their captured reason and
summary so a human can follow up with full context. Read-only in v1. The backend
derives ``tenant_id`` from the verified JWT (the client takes no ``tenant_id``);
an empty tenant renders a designed empty state.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Escalations</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Conversations your agent handed off to a human, '
        "newest first. Scoped to your tenant only.</p>",
        unsafe_allow_html=True,
    )

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(4)
    try:
        escalations = client.list_escalations(limit=200)
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
            "No escalations yet",
            description="When the agent hands a conversation to a human, it will "
            "appear here with the reason and context.",
            icon="🚩",
        )
        return

    for esc in escalations:
        with st.expander(f"{esc.reason[:80]}  —  {esc.updated_at}"):
            st.markdown(f"**Conversation:** `{esc.conversation_id}`")
            st.markdown(f"**Status:** {esc.conversation_status}")
            st.markdown("**Reason**")
            st.write(esc.reason)
            st.markdown("**Summary**")
            st.write(esc.summary or "_(none provided)_")


if __name__ == "__main__":
    main()
