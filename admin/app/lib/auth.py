"""Streamlit-side auth helpers.

The admin app authenticates via the backend's existing JWT login
(``POST /api/v1/auth/login``). We hold the resulting ``{token, expires_at}``
pair in ``st.session_state`` for the duration of the Streamlit session
only — never persisted to disk / cookies / localStorage (FR-010b mirror:
keep tenant-scoped credentials out of long-term storage).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib.theme import callout


_TOKEN_KEY = "albert.token"
_TOKEN_EXP_KEY = "albert.token_exp"
_EMAIL_KEY = "albert.email"
_ROLE_KEY = "albert.platform_role"


@dataclass(frozen=True)
class Session:
    token: str
    email: str
    expires_at: float


def current_session() -> Session | None:
    token = st.session_state.get(_TOKEN_KEY)
    if not token:
        return None
    expires_at = float(st.session_state.get(_TOKEN_EXP_KEY, 0))
    if expires_at and expires_at < time.time():
        # Expired token: drop it so the next render shows the login form.
        clear_session()
        return None
    return Session(
        token=token,
        email=str(st.session_state.get(_EMAIL_KEY, "")),
        expires_at=expires_at,
    )


def store_session(token: str, *, email: str, ttl_seconds: int = 3600) -> None:
    st.session_state[_TOKEN_KEY] = token
    st.session_state[_TOKEN_EXP_KEY] = time.time() + ttl_seconds
    st.session_state[_EMAIL_KEY] = email


def clear_session() -> None:
    for key in (_TOKEN_KEY, _TOKEN_EXP_KEY, _EMAIL_KEY, _ROLE_KEY):
        st.session_state.pop(key, None)


def _block_platform_managers(client: BackendClient) -> None:
    """Stop rendering with a clear notice if the signed-in user is a platform
    manager. This console manages a single tenant's widgets/origins/config —
    a ``tenant_manager`` has no tenant membership and would only hit 403s here.
    The platform role is resolved from ``/auth/me`` (cached per session)."""
    role = st.session_state.get(_ROLE_KEY)
    if role is None:
        try:
            role = client.me().get("role") or ""
        except BackendError:
            # Don't hard-block on a transient error — feature pages will surface
            # the real backend error if one persists.
            return
        st.session_state[_ROLE_KEY] = role
    if role == "tenant_manager":
        callout(
            "You're signed in as a <strong>platform manager</strong>. This console "
            "manages a single tenant's widgets, origins, and guardrails — managers "
            "operate at the platform level (provision/suspend/erase tenants, aggregate "
            "usage) and intentionally cannot access tenant content here. "
            "Sign in as a tenant admin (e.g. <code>admin-acme@example.com</code>) to "
            "manage Acme's widgets.",
            level="warning",
        )
        if st.button("Sign out", key="albert-mgr-signout"):
            clear_session()
            st.rerun()
        st.stop()


def login_form(client: BackendClient) -> Session | None:
    """Render the login form. Returns a Session once the user authenticates.

    Stays minimal on purpose — admins log in once per session; the surface
    is one card with email + password + a single primary CTA.
    """
    st.markdown("<h1>Sign in to Albert</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Use your tenant admin credentials. '
        "Sessions live in memory only; closing this tab signs you out.</p>",
        unsafe_allow_html=True,
    )

    with st.form("albert-login", clear_on_submit=False):
        email = st.text_input("Email", autocomplete="email")
        password = st.text_input(
            "Password", type="password", autocomplete="current-password"
        )
        submitted = st.form_submit_button("Sign in", type="primary")

    if not submitted:
        return None

    if not email or not password:
        callout("Email and password are both required.", level="danger")
        return None

    try:
        token = client.login(email=email, password=password)
    except BackendError as exc:
        callout(f"Sign-in failed: {exc}", level="danger")
        return None

    store_session(token, email=email)
    st.rerun()
    return None  # unreachable — st.rerun() halts execution


def require_session(client: BackendClient) -> Session:
    """Top-of-page guard: render the login form if not signed in, else return.

    Also binds the token to ``client`` and blocks platform managers with a clear
    notice (this is a tenant-admin console), so every page has one chokepoint.
    """
    session = current_session()
    if session is None:
        login_form(client)
        st.stop()
    client.token = session.token  # type: ignore[union-attr]
    _block_platform_managers(client)
    return session  # type: ignore[return-value]


def render_sidebar_account(session: Session) -> None:
    """Account block in the sidebar — email + a single sign-out button."""
    with st.sidebar:
        st.markdown("---")
        st.markdown(
            f'<div class="albert-meta">Signed in as<br>'
            f'<strong>{session.email}</strong></div>',
            unsafe_allow_html=True,
        )
        if st.button("Sign out", key="albert-signout"):
            clear_session()
            st.rerun()
