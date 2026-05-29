"""Managers — list the current manager + create a new platform manager (FR-017).

There is no list-managers endpoint today, so v1 surfaces the signed-in manager
plus a "Create manager" form (``create_manager``). Newly created managers are
shown for the session so the operator gets immediate confirmation.
"""

from __future__ import annotations

import re

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CREATED_KEY = "albert.created_managers"


def _validate_email(value: str) -> str | None:
    return None if _EMAIL_RE.match(value.strip()) else "Enter a valid email address."


def _validate_password(value: str) -> str | None:
    return None if len(value) >= 8 else "Password must be at least 8 characters."


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)
    st.markdown(
        "<h1>Managers</h1>"
        '<p class="albert-meta">Platform managers have lifecycle and aggregate '
        "power only — never tenant content.</p>",
        unsafe_allow_html=True,
    )

    created = st.session_state.get(_CREATED_KEY, [])

    st.markdown("<h2>Current managers</h2>", unsafe_allow_html=True)
    rows = [[session.email, "you (signed in)"]]
    rows.extend([[email, "created this session"] for email in created])
    ui.data_table(["Email", "Note"], rows)

    st.markdown("<h2>Create manager</h2>", unsafe_allow_html=True)
    email, email_ok = ui.inline_validated_input(
        "New manager email", validator=_validate_email, key="cm-email"
    )
    password, pw_ok = ui.inline_validated_input(
        "Temporary password",
        validator=_validate_password,
        key="cm-pw",
        password=True,
        help="At least 8 characters. The new manager can change it after signing in.",
    )
    if st.button("Create manager", type="primary", disabled=not (email_ok and pw_ok)):
        try:
            manager = client.create_manager(email=email.strip(), password=password)
        except BackendError as exc:
            if not handle_backend_error(exc):
                st.error(f"Could not create manager: {exc}")
            return
        st.session_state.setdefault(_CREATED_KEY, []).append(manager.email)
        st.success(f"Created manager {manager.email}.")
        st.rerun()


if __name__ == "__main__":
    main()
