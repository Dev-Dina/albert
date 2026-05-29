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
from typing import Literal

import streamlit as st

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
)
from app.lib.theme import callout


_TOKEN_KEY = "albert.token"
_TOKEN_EXP_KEY = "albert.token_exp"
_EMAIL_KEY = "albert.email"

# Cached identity (role + tenant) keyed by the token it was resolved for, so a
# signed-in user is probed once per token rather than on every Streamlit rerun.
_ROLE_KEY = "albert.role"
_TENANT_ID_KEY = "albert.tenant_id"
_TENANT_NAME_KEY = "albert.tenant_name"
_IDENTITY_TOKEN_KEY = "albert.identity_token"

Role = Literal["tenant_manager", "tenant_admin", "other"]


@dataclass(frozen=True)
class Session:
    token: str
    email: str
    expires_at: float
    role: Role = "other"
    tenant_id: str | None = None
    tenant_name: str | None = None

    def __post_init__(self) -> None:
        """Enforce the role/tenant invariant (data-model.md).

        ``tenant_manager`` → ``tenant_id``/``tenant_name`` MUST be ``None``.
        ``tenant_admin`` → ``tenant_id`` MUST be present, else the session is
        invalid and degrades to ``other`` (renders the wrong-role view).
        Anything else (``member`` / unknown) is ``other`` with no tenant.
        """
        if self.role == "tenant_manager":
            object.__setattr__(self, "tenant_id", None)
            object.__setattr__(self, "tenant_name", None)
        elif self.role == "tenant_admin":
            if not self.tenant_id:
                object.__setattr__(self, "role", "other")
                object.__setattr__(self, "tenant_name", None)
        else:
            object.__setattr__(self, "role", "other")
            object.__setattr__(self, "tenant_id", None)
            object.__setattr__(self, "tenant_name", None)


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
    for key in (
        _TOKEN_KEY,
        _TOKEN_EXP_KEY,
        _EMAIL_KEY,
        _ROLE_KEY,
        _TENANT_ID_KEY,
        _TENANT_NAME_KEY,
        _IDENTITY_TOKEN_KEY,
    ):
        st.session_state.pop(key, None)


def resolve_identity(client: BackendClient) -> Session | None:
    """Probe ``GET /auth/me`` and return the role-aware :class:`Session`.

    Returns ``None`` when there is no (valid) token — the caller renders the
    login form. The verified role + tenant come from the backend; the JWT is
    never decoded locally (FR-001, admin_session_contract.md). The identity is
    cached in ``st.session_state`` keyed by the current token so we probe once
    per token, not on every rerun.

    Failure modes (admin_session_contract.md): 401 →
    :class:`BackendUnauthorizedError` is caught here, the session is cleared,
    and ``None`` is returned (login form). 5xx / network errors propagate as
    :class:`BackendError` for the caller's retryable error state.
    """
    base = current_session()
    if base is None:
        return None

    if st.session_state.get(_IDENTITY_TOKEN_KEY) == base.token:
        return _session_with_identity(
            base,
            role=st.session_state.get(_ROLE_KEY, "other"),
            tenant_id=st.session_state.get(_TENANT_ID_KEY),
            tenant_name=st.session_state.get(_TENANT_NAME_KEY),
        )

    try:
        identity = client.auth_me()
    except BackendUnauthorizedError:
        clear_session()
        return None

    st.session_state[_ROLE_KEY] = identity.role
    st.session_state[_TENANT_ID_KEY] = identity.tenant_id
    st.session_state[_TENANT_NAME_KEY] = identity.tenant_name
    st.session_state[_IDENTITY_TOKEN_KEY] = base.token
    return _session_with_identity(
        base,
        role=identity.role,
        tenant_id=identity.tenant_id,
        tenant_name=identity.tenant_name,
    )


def _session_with_identity(
    base: Session,
    *,
    role: str,
    tenant_id: str | None,
    tenant_name: str | None,
) -> Session:
    # Session.__post_init__ normalizes any non-manager/admin role to "other".
    normalized_role: Role = role if role in ("tenant_manager", "tenant_admin") else "other"
    return Session(
        token=base.token,
        email=base.email,
        expires_at=base.expires_at,
        role=normalized_role,
        tenant_id=tenant_id,
        tenant_name=tenant_name,
    )


def page_session() -> Session:
    """Top-of-page guard for role pages run via ``st.navigation``.

    ``main.py`` has already verified identity before routing here; this re-reads
    the in-memory session so a page can build an authed client. If the session
    expired between reruns, stop and let the next rerun fall back to login.
    """
    session = current_session()
    if session is None:
        st.warning("Your session expired. Reloading the sign-in screen…")
        st.rerun()
    return session  # type: ignore[return-value]


# Markers that a tenant-scoped response signals the tenant is no longer active
# (suspended/erased after sign-in). Matched against the backend error message
# for the statuses a status-aware endpoint would use.
_TENANT_INACTIVE_MARKERS = ("suspend", "eras", "inactive", "not active")


def _is_tenant_inactive(exc: BackendError) -> bool:
    if isinstance(exc, BackendUnauthorizedError):
        return False
    message = (exc.message or "").lower()
    return exc.status_code in (403, 409, 423) and any(
        marker in message for marker in _TENANT_INACTIVE_MARKERS
    )


def render_tenant_inactive_banner() -> None:
    """Designed banner for the 'tenant suspended/erased after sign-in' edge case.

    Explicit, not a blank page (spec edge cases): explains the state and offers
    a sign-out. No tenant data is loaded behind it.
    """
    callout(
        "This tenant is no longer active. It was suspended or erased by the "
        "platform after you signed in, so its admin surface is unavailable. "
        "This mirrors the backend's access boundary — no tenant data is loaded.",
        level="danger",
    )
    if st.button("Sign out", key="albert-tenant-inactive-signout", type="primary"):
        clear_session()
        st.rerun()


def handle_backend_error(exc: BackendError) -> bool:
    """Centralized backend-error handling for pages (data-model cross-cutting).

    On 401 (expired/invalid token) clears the session and reruns so the app
    falls back to the login form, and returns True (handled). When a response
    signals the tenant is no longer active (suspended/erased after sign-in),
    renders the designed inactive banner and returns True. For any other error
    returns False so the caller can render its own retryable error state.
    """
    if isinstance(exc, BackendUnauthorizedError):
        clear_session()
        st.rerun()
        return True
    if _is_tenant_inactive(exc):
        render_tenant_inactive_banner()
        return True
    return False


def render_wrong_role_view(session: Session) -> None:
    """Render the static wrong-role / unknown-role view (FR-004, FR-005).

    Mirrors the backend's 403 boundary: a fixed client-side explanation plus a
    sign-out control only. Makes NO backend call and offers no auto-redirect.
    """
    st.markdown("<h1>This account has no admin surface</h1>", unsafe_allow_html=True)
    callout(
        "Your account is signed in, but it is not a platform manager or a "
        "tenant admin, so there is nothing to administer here. This mirrors "
        "the backend's access boundary — no tenant or platform data is loaded. "
        "If you believe this is an error, contact your administrator.",
        level="info",
    )
    if st.button("Sign out", key="albert-wrong-role-signout", type="primary"):
        clear_session()
        st.rerun()


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
    """Top-of-page guard: render the login form if not signed in, else return."""
    session = current_session()
    if session is None:
        login_form(client)
        st.stop()
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
