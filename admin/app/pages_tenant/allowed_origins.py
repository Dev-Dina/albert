"""Allowed Origins page — list, add, remove.

Migrated from ``pages/2_Allowed_Origins.py`` to the ``st.navigation`` model.
The empty-state warning is mandatory (FR-014 mirror): when the allowlist is
empty the page names the consequence ("no widget will load anywhere until at
least one origin is added") and links to Widgets. All prior actions preserved.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import callout, section


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Allowed origins</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Exact origins (scheme + host + port) where your '
        "widget is allowed to load. No wildcards, no paths.</p>",
        unsafe_allow_html=True,
    )

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(2)

    try:
        origins = client.list_allowed_origins()
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load allowed origins: {exc}", key="origins-retry"):
            st.rerun()
        return

    slot.empty()

    if not origins:
        callout(
            "No allowed origins configured. <strong>No widget will load anywhere</strong> "
            "until at least one origin is added — the token-exchange endpoint rejects "
            "every request without an allowlist match.",
            level="warning",
        )
        st.page_link(
            "pages_tenant/widgets.py",
            label="See widgets that are currently un-embeddable",
            icon="🪟",
        )

    section("Add an origin")
    with st.form("add-origin", clear_on_submit=True):
        col_input, col_button = st.columns([4, 1], gap="small")
        with col_input:
            new_origin = st.text_input(
                "Origin",
                placeholder="https://www.example.com",
                label_visibility="collapsed",
                help=(
                    "Examples: https://www.example.com · https://shop.example.com:8443 "
                    "· http://localhost:8080. No paths, no wildcards, no trailing slashes."
                ),
            )
        with col_button:
            add = st.form_submit_button("Add", type="primary")
    if add:
        if not new_origin.strip():
            callout("Origin is required.", level="danger")
        else:
            try:
                client.add_allowed_origin(new_origin.strip())
            except BackendError as exc:
                if handle_backend_error(exc):
                    return
                callout(
                    f"Could not add origin (likely invalid format): {exc}",
                    level="danger",
                )
            else:
                st.rerun()

    section("Current origins")
    if not origins:
        return
    for o in origins:
        with st.container():
            st.markdown('<div class="albert-section">', unsafe_allow_html=True)
            left, right = st.columns([4, 1])
            with left:
                st.markdown(
                    f'<div class="albert-mono" style="font-size:1rem;">{o.origin}</div>',
                    unsafe_allow_html=True,
                )
            with right:
                if st.button("Remove", key=f"remove-{o.id}", type="secondary"):
                    try:
                        client.delete_allowed_origin(o.id)
                    except BackendError as exc:
                        if handle_backend_error(exc):
                            return
                        callout(f"Could not remove origin: {exc}", level="danger")
                    else:
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
