"""Signing key page — view current version + rotate-only action.

Rotation invalidates every outstanding session token for this tenant in one
action. We gate the rotate button behind a two-step confirmation so admins
can't trigger it accidentally — the confirmation banner spells out the
consequence in plain English.

The current key version is fetched from the backend on every render so the
panel always reflects the live state (not just rotations done in this
Streamlit session).
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
)
from app.lib.auth import clear_session, render_sidebar_account, require_session
from app.lib.theme import COLORS, apply_page_chrome, callout, section


_CONFIRM_KEY = "albert.rotate_confirm"
_LAST_FLASH_KEY = "albert.rotate_flash"


def _render_current(client: BackendClient) -> None:
    try:
        meta = client.get_signing_key()
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return
    except BackendError as exc:
        callout(f"Could not load current key metadata: {exc}", level="danger")
        return

    section("Current signing key")
    if meta is None:
        callout(
            "No active signing key for this tenant yet. Rotate below to mint v1.",
            level="warning",
        )
        return

    # Open the bento card, then use Streamlit columns for the two-column
    # layout (more reliable than a flexbox inside a single markdown call —
    # Streamlit's sanitiser sometimes drops sibling divs after a colored
    # span). Close the card after the columns render.
    st.markdown('<div class="albert-section">', unsafe_allow_html=True)
    col_v, col_t = st.columns([1, 2], gap="large")
    with col_v:
        st.markdown(
            f'<div class="albert-meta">Active version</div>'
            f'<div class="albert-mono" '
            f'style="font-size:2rem; color:{COLORS["primary"]}; font-weight:700; line-height:1.1;">'
            f"v{meta.version}</div>",
            unsafe_allow_html=True,
        )
    with col_t:
        st.markdown(
            f'<div class="albert-meta">Created at</div>'
            f'<div class="albert-mono" style="font-size:1rem;">{meta.created_at}</div>',
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_rotate(client: BackendClient) -> None:
    section("Rotate signing key")

    flash = st.session_state.pop(_LAST_FLASH_KEY, None)
    if flash is not None:
        st.success(flash)

    confirming = bool(st.session_state.get(_CONFIRM_KEY))

    if not confirming:
        callout(
            "Rotating the signing key will sign every visitor out of every widget "
            "on this tenant. They'll silently re-authenticate on their next request, "
            "but anyone mid-message will see a brief reconnection.",
            level="warning",
        )
        if st.button("Rotate signing key…", type="primary"):
            st.session_state[_CONFIRM_KEY] = True
            st.rerun()
        return

    callout(
        "<strong>Are you sure?</strong> This action will sign every visitor "
        "out of every widget on this tenant. It cannot be undone.",
        level="danger",
    )
    col_cancel, col_confirm = st.columns([1, 1])
    with col_cancel:
        if st.button("Cancel", type="secondary"):
            st.session_state[_CONFIRM_KEY] = False
            st.rerun()
    with col_confirm:
        if st.button("Yes, rotate now", type="primary"):
            try:
                meta = client.rotate_signing_key()
            except BackendUnauthorizedError:
                clear_session()
                st.rerun()
                return
            except BackendError as exc:
                callout(f"Rotation failed: {exc}", level="danger")
                st.session_state[_CONFIRM_KEY] = False
                return
            st.session_state[_CONFIRM_KEY] = False
            st.session_state[_LAST_FLASH_KEY] = (
                f"Rotated to version v{meta.version} "
                f"(created at {meta.created_at})."
            )
            st.rerun()


def main() -> None:
    apply_page_chrome("Signing key", icon="🔑")
    client = BackendClient()
    session = require_session(client)
    client.token = session.token
    render_sidebar_account(session)

    st.markdown("<h1>Signing key</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Your tenant\'s widget signing key signs every '
        "visitor session token. Rotating it invalidates every outstanding "
        "session — every active visitor will silently re-authenticate on "
        "their next request.</p>",
        unsafe_allow_html=True,
    )

    _render_current(client)
    _render_rotate(client)


if __name__ == "__main__":
    main()
