"""Signing Key page — view current version + rotate-only action.

Migrated from ``pages/5_Signing_Key.py`` to the ``st.navigation`` model and
extended with an explicit state indicator (FR-022, US2 scenario 3). The state
is derived from the response shape rather than inferred from absence:

* a key version present  → ``active``
* a key with ``rotated_at`` set (future field) → ``rotated``
* a key not yet promoted (future ``pending`` field) → ``pending``
* no key at all → ``none`` (rotate to mint v1)

The v1 backend endpoint returns only the active key's ``{version, created_at}``,
so today the live states are ``active`` / ``none``; the helper already maps the
richer states so a future response shape needs no page change.
"""

from __future__ import annotations

from typing import Any

import streamlit as st

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    SigningKeyMeta,
)
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import COLORS, callout, section, status_badge


_CONFIRM_KEY = "albert.rotate_confirm"
_LAST_FLASH_KEY = "albert.rotate_flash"


def signing_key_state(meta: SigningKeyMeta | None) -> str:
    """Derive an explicit lifecycle state from the response fields (FR-022)."""
    if meta is None:
        return "none"
    if getattr(meta, "rotated_at", None):
        return "rotated"
    if getattr(meta, "pending", False):
        return "pending"
    return "active"


def _render_current(client: BackendClient) -> None:
    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(2)
    try:
        meta = client.get_signing_key()
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load current key metadata: {exc}", key="key-retry"):
            st.rerun()
        return

    slot.empty()
    section("Current signing key")
    state = signing_key_state(meta)
    st.markdown(
        f'<div style="margin-bottom:0.5rem;">State: {status_badge(state)}</div>',
        unsafe_allow_html=True,
    )

    if meta is None:
        callout(
            "No active signing key for this tenant yet. Rotate below to mint v1.",
            level="warning",
        )
        return

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
            except BackendError as exc:
                if handle_backend_error(exc):
                    return
                callout(f"Rotation failed: {exc}", level="danger")
                st.session_state[_CONFIRM_KEY] = False
                return
            st.session_state[_CONFIRM_KEY] = False
            st.session_state[_LAST_FLASH_KEY] = (
                f"Rotated to version v{meta.version} (created at {meta.created_at})."
            )
            st.rerun()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

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
