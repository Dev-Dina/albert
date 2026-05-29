"""Albert admin entry point — role-aware navigation.

After sign-in the app probes the verified identity from the backend
(``GET /auth/me``) — never from a UI toggle, a query param, or by decoding the
JWT locally — then registers ONLY the resolved role's pages via
``st.navigation``. Cross-role / unknown identities get the static wrong-role
view. Pages live under ``pages_platform/`` and ``pages_tenant/`` (not
Streamlit's auto-discovered ``pages/``) so the wrong role's surface is never
enumerable in the sidebar (FR-001, FR-002, FR-003).
"""

from __future__ import annotations

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib.auth import (
    Session,
    current_session,
    login_form,
    render_sidebar_account,
    render_wrong_role_view,
    resolve_identity,
)
from app.lib.nav import build_navigation
from app.lib.theme import apply_page_chrome
from app.lib.ui import error_state


def _get_client(token: str | None = None) -> BackendClient:
    return BackendClient(token=token)


def _render_role_badge(session: Session) -> None:
    """Sidebar badge: 'Platform' for managers, 'Tenant: <name>' for admins."""
    if session.role == "tenant_manager":
        label, css_class = "Platform", "albert-badge-muted"
    elif session.role == "tenant_admin":
        label = f"Tenant: {session.tenant_name or '—'}"
        css_class = "albert-badge-success"
    else:
        return
    with st.sidebar:
        st.markdown(
            f'<div style="margin-bottom:0.5rem;">'
            f'<span class="albert-badge {css_class}">{label}</span></div>',
            unsafe_allow_html=True,
        )


def main() -> None:
    apply_page_chrome("Admin")

    base = current_session()
    if base is None:
        login_form(_get_client())
        return

    client = _get_client(token=base.token)
    try:
        session = resolve_identity(client)
    except BackendError as exc:
        # 5xx / network during the identity probe — retryable error state.
        if error_state(
            f"Couldn't load your account from the backend: {exc}",
            key="albert-identity-retry",
        ):
            st.rerun()
        return

    if session is None:
        # Token was rejected (401) and the session cleared — show login again.
        login_form(_get_client())
        return

    render_sidebar_account(session)
    _render_role_badge(session)

    if session.role == "other":
        render_wrong_role_view(session)
        return

    navigation = st.navigation(build_navigation(session.role))
    navigation.run()


if __name__ == "__main__":
    main()
