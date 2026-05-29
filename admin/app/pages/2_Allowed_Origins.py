"""Allowed Origins page — list, add, remove.

Empty-state warning is mandatory (FR-014 mirror): when the allowlist is
empty, the page renders a prominent banner naming the consequence ("no
widget will load anywhere until at least one origin is added") and links
to the Widgets page so the admin can see which widgets are currently
un-embeddable.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
)
from app.lib.auth import clear_session, render_sidebar_account, require_session
from app.lib.theme import apply_page_chrome, callout, section

# The widget iframe + its session token-exchange both run from the Albert backend
# origin, so that origin must be allow-listed for the widget to load locally.
_LOCAL_PREVIEW_ORIGIN = "http://localhost:8000"


def _normalize_origin(raw: str) -> str:
    """Light client-side cleanup so common paste mistakes don't bounce as 422.

    Trims whitespace and a trailing slash (the backend rejects trailing slashes).
    Genuine paths/queries are left intact so the backend still returns a clear
    validation error rather than us silently mangling the value.
    """
    return raw.strip().rstrip("/")


def _add_origin(client: BackendClient, origin: str) -> bool:
    try:
        client.add_allowed_origin(origin)
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return False
    except BackendError as exc:
        callout(
            f"Could not add <code>{origin}</code> — origins must be "
            f"<code>scheme://host[:port]</code> with no path or trailing slash. {exc}",
            level="danger",
        )
        return False
    return True


def main() -> None:
    apply_page_chrome("Allowed origins", icon="🛡️")
    client = BackendClient()
    session = require_session(client)
    client.token = session.token
    render_sidebar_account(session)

    st.markdown("<h1>Allowed origins</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Exact origins (scheme + host + port) where your '
        "widget is allowed to load. No wildcards, no paths.</p>",
        unsafe_allow_html=True,
    )

    try:
        origins = client.list_allowed_origins()
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return
    except BackendError as exc:
        callout(f"Could not load allowed origins: {exc}", level="danger")
        return

    if not origins:
        callout(
            "No allowed origins configured. <strong>No widget will load anywhere</strong> "
            "until at least one origin is added — the token-exchange endpoint rejects "
            "every request without an allowlist match.",
            level="warning",
        )
        st.page_link(
            "pages/1_Widgets.py",
            label="See widgets that are currently un-embeddable",
            icon="🪟",
        )

    callout(
        "<strong>Local preview tip:</strong> the widget iframe and its session "
        f"token-exchange run from the Albert backend origin, so add "
        f"<code>{_LOCAL_PREVIEW_ORIGIN}</code> to preview the widget locally "
        "(open the backend embed page directly). To embed on your own page, also "
        "add that page's origin (e.g. <code>http://localhost:8080</code>) — it's "
        "needed so the browser allows the widget to be framed there.",
        level="info",
    )

    has_preview_origin = any(o.origin == _LOCAL_PREVIEW_ORIGIN for o in origins)
    if not has_preview_origin:
        if st.button(f"Add {_LOCAL_PREVIEW_ORIGIN} (for local preview)", type="secondary"):
            if _add_origin(client, _LOCAL_PREVIEW_ORIGIN):
                st.rerun()

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
                    "· http://localhost:8080. No paths, no wildcards, no trailing slashes "
                    "(a trailing slash is trimmed automatically)."
                ),
            )
        with col_button:
            add = st.form_submit_button("Add", type="primary")
    if add:
        origin = _normalize_origin(new_origin)
        if not origin:
            callout("Origin is required.", level="danger")
        elif _add_origin(client, origin):
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
                if st.button(
                    "Remove",
                    key=f"remove-{o.id}",
                    type="secondary",
                ):
                    try:
                        client.delete_allowed_origin(o.id)
                    except BackendError as exc:
                        callout(f"Could not remove origin: {exc}", level="danger")
                    else:
                        st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    main()
