"""Albert tenant-admin entry page.

Streamlit auto-discovers the per-feature pages under ``pages/``; this file
hosts the landing / overview surface and the sign-in form. The shared
chrome (theme + sidebar account block) lives in ``app.lib`` so every page
can import it.
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib.auth import (
    render_sidebar_account,
    require_session,
)
from app.lib.theme import (
    apply_page_chrome,
    callout,
    section,
)


def _get_client(token: str | None = None) -> BackendClient:
    return BackendClient(token=token)


def _overview(session) -> None:
    client = _get_client(token=session.token)

    st.markdown(
        '<h1>Tenant admin overview</h1>'
        '<p class="albert-meta">Manage your widgets, allowed origins, '
        "guardrails, and signing keys. Open a section from the left sidebar.</p>",
        unsafe_allow_html=True,
    )

    # Lightweight status snapshot — the bento grid lives here. Each card is
    # a single section with one primary metric and one secondary line.
    try:
        widgets = client.list_widgets()
        origins = client.list_allowed_origins()
    except BackendError as exc:
        callout(f"Could not load overview: {exc}", level="danger")
        return

    enabled = sum(1 for w in widgets if w.status == "enabled")
    disabled = len(widgets) - enabled

    col_w, col_o, col_g = st.columns(3, gap="medium")
    with col_w:
        section("Widgets")
        st.markdown(
            f'<div class="albert-mono" style="font-size:2rem;">{len(widgets)}</div>'
            f'<div class="albert-meta">{enabled} enabled · {disabled} disabled</div>',
            unsafe_allow_html=True,
        )
    with col_o:
        section("Allowed origins")
        st.markdown(
            f'<div class="albert-mono" style="font-size:2rem;">{len(origins)}</div>'
            f'<div class="albert-meta">Sites your widget will load from</div>',
            unsafe_allow_html=True,
        )
        if not origins:
            callout(
                "No allowed origins configured — your widget cannot load anywhere.",
                level="warning",
            )
    with col_g:
        section("Quick actions")
        st.page_link("pages/1_Widgets.py", label="Manage widgets", icon="🪟")
        st.page_link("pages/2_Allowed_Origins.py", label="Edit allowlist", icon="🛡️")
        st.page_link("pages/4_Embed_Snippet.py", label="Copy embed snippet", icon="📋")


def main() -> None:
    apply_page_chrome("Overview", icon="🟦")
    client = _get_client()
    session = require_session(client)
    render_sidebar_account(session)
    _overview(session)


if __name__ == "__main__":
    main()
