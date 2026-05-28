"""Widgets page — list, create, edit name/theme/greeting/status."""

from __future__ import annotations

import json

import streamlit as st

from app.clients.backend_client import (
    AdminWidget,
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
)
from app.lib.auth import clear_session, render_sidebar_account, require_session
from app.lib.theme import apply_page_chrome, callout, section, status_badge


def _render_widget_row(client: BackendClient, widget: AdminWidget, *, allowlist_empty: bool) -> None:
    with st.container():
        st.markdown('<div class="albert-section">', unsafe_allow_html=True)
        head_left, head_right = st.columns([3, 1])
        with head_left:
            st.markdown(
                f"<h3>{widget.name}</h3>"
                f'<div class="albert-mono albert-meta">{widget.public_widget_id}</div>',
                unsafe_allow_html=True,
            )
        with head_right:
            badge = status_badge(widget.status)
            if allowlist_empty:
                badge += ' <span class="albert-badge albert-badge-warning">no allowed origins</span>'
            st.markdown(
                f'<div style="text-align:right;">{badge}</div>',
                unsafe_allow_html=True,
            )

        with st.expander("Edit details", expanded=False):
            with st.form(f"edit-{widget.id}", clear_on_submit=False):
                new_name = st.text_input("Name", value=widget.name)
                new_greeting = st.text_area(
                    "Greeting", value=widget.greeting,
                    max_chars=500,
                    help="Visible to visitors as the first chat message.",
                )
                theme_json = st.text_area(
                    "Theme (JSON)",
                    value=json.dumps(widget.theme, indent=2) if widget.theme else "{}",
                    help='Example: {"primary_color": "#2563eb"}',
                )
                new_status = st.selectbox(
                    "Status",
                    options=["enabled", "disabled"],
                    index=0 if widget.status == "enabled" else 1,
                )
                submit = st.form_submit_button("Save changes", type="primary")

            if submit:
                try:
                    parsed_theme = json.loads(theme_json) if theme_json.strip() else {}
                    if not isinstance(parsed_theme, dict):
                        raise ValueError("Theme must be a JSON object.")
                except ValueError as exc:
                    callout(f"Invalid theme JSON: {exc}", level="danger")
                    return
                try:
                    client.update_widget(
                        widget.id,
                        name=new_name,
                        greeting=new_greeting,
                        theme=parsed_theme,
                        status=new_status,
                    )
                except BackendUnauthorizedError:
                    clear_session()
                    st.rerun()
                except BackendError as exc:
                    callout(f"Could not save changes: {exc}", level="danger")
                    return
                st.success("Saved. Reload the host page to see the new values.")
                st.rerun()

        st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    apply_page_chrome("Widgets", icon="🪟")
    client = BackendClient()
    session = require_session(client)
    client.token = session.token
    render_sidebar_account(session)

    st.markdown("<h1>Widgets</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">A widget is one embeddable chat instance. '
        "Each carries its own greeting, theme, and status.</p>",
        unsafe_allow_html=True,
    )

    try:
        widgets = client.list_widgets()
        allowed_origins = client.list_allowed_origins()
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return
    except BackendError as exc:
        callout(f"Could not load widgets: {exc}", level="danger")
        return

    allowlist_empty = len(allowed_origins) == 0
    if allowlist_empty:
        callout(
            "Your allowed-origins list is empty — every widget below will refuse to load. "
            "Add at least one origin on the Allowed Origins page.",
            level="warning",
        )

    section("Create a new widget")
    with st.form("create-widget", clear_on_submit=True):
        new_name = st.text_input("Name", max_chars=100)
        new_greeting = st.text_area("Greeting (optional)", max_chars=500)
        create = st.form_submit_button("Create widget", type="primary")
    if create:
        if not new_name.strip():
            callout("Name is required.", level="danger")
        else:
            try:
                client.create_widget(name=new_name, greeting=new_greeting)
            except BackendError as exc:
                callout(f"Could not create widget: {exc}", level="danger")
            else:
                st.rerun()

    section("Your widgets")
    if not widgets:
        st.markdown(
            '<div class="albert-callout albert-callout-info">'
            "No widgets yet. Create one above to get started.</div>",
            unsafe_allow_html=True,
        )
        return
    for widget in widgets:
        _render_widget_row(client, widget, allowlist_empty=allowlist_empty)


if __name__ == "__main__":
    main()
