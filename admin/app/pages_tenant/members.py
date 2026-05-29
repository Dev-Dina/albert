"""Members page — list / invite / remove tenant members (FR-024, US2 scenario 5).

Lists ``role='member'`` rows for this tenant (the client method takes no
``tenant_id`` argument — scope comes from the JWT). Invite uses an inline-
validated email + password form; remove sits behind a simple per-row confirm
(typed-slug confirm is NOT required for members — FR-013 covers tenant
lifecycle only). The caller's own row is marked non-removable.
"""

from __future__ import annotations

import re

import streamlit as st

from app.clients.backend_client import BackendClient, BackendError
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import callout, section

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_CONFIRM_KEY = "albert.member_remove_confirm"


def _validate_email(value: str) -> str | None:
    return None if _EMAIL_RE.match(value.strip()) else "Enter a valid email address."


def _validate_password(value: str) -> str | None:
    return None if len(value) >= 8 else "Password must be at least 8 characters."


def _render_member_row(client: BackendClient, member, *, is_self: bool) -> None:
    with st.container():
        st.markdown('<div class="albert-section">', unsafe_allow_html=True)
        left, right = st.columns([4, 1])
        with left:
            self_tag = ' <span class="albert-badge albert-badge-muted">you</span>' if is_self else ""
            st.markdown(
                f'<div style="font-size:1rem;">{member.email}{self_tag}</div>'
                f'<div class="albert-meta">added {member.created_at}</div>',
                unsafe_allow_html=True,
            )
        with right:
            if is_self:
                st.markdown(
                    '<div class="albert-meta" style="text-align:right;">non-removable</div>',
                    unsafe_allow_html=True,
                )
            else:
                _render_remove_control(client, member)
        st.markdown("</div>", unsafe_allow_html=True)


def _render_remove_control(client: BackendClient, member) -> None:
    confirming = st.session_state.get(_CONFIRM_KEY) == member.user_id
    if not confirming:
        if st.button("Remove", key=f"rm-{member.user_id}", type="secondary"):
            st.session_state[_CONFIRM_KEY] = member.user_id
            st.rerun()
        return

    st.markdown(
        '<div class="albert-meta">Remove this member?</div>', unsafe_allow_html=True
    )
    col_yes, col_no = st.columns(2)
    with col_no:
        if st.button("Cancel", key=f"rm-cancel-{member.user_id}"):
            st.session_state.pop(_CONFIRM_KEY, None)
            st.rerun()
    with col_yes:
        if st.button("Confirm", key=f"rm-confirm-{member.user_id}", type="primary"):
            try:
                client.remove_member(member.user_id)
            except BackendError as exc:
                if handle_backend_error(exc):
                    return
                callout(f"Could not remove member: {exc}", level="danger")
                return
            st.session_state.pop(_CONFIRM_KEY, None)
            st.rerun()


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Members</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Members of your tenant. Inviting creates a login; '
        "removing revokes access (the user account itself is preserved).</p>",
        unsafe_allow_html=True,
    )

    section("Invite a member")
    email, email_ok = ui.inline_validated_input(
        "Member email", validator=_validate_email, key="inv-email"
    )
    password, pw_ok = ui.inline_validated_input(
        "Temporary password",
        validator=_validate_password,
        key="inv-pw",
        password=True,
        help="At least 8 characters. The member can change it after signing in.",
    )
    if st.button("Invite member", type="primary", disabled=not (email_ok and pw_ok)):
        try:
            client.invite_member(email=email.strip(), password=password)
        except BackendError as exc:
            if handle_backend_error(exc):
                return
            callout(f"Could not invite member: {exc}", level="danger")
        else:
            st.success(f"Invited {email.strip()}.")
            st.rerun()

    section("Current members")
    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(3)

    try:
        members = client.list_members()
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load members: {exc}", key="members-retry"):
            st.rerun()
        return

    slot.empty()

    if not members:
        ui.empty_state(
            "No members yet",
            description="Invite your first member with the form above.",
            icon="👥",
        )
        return

    for member in members:
        _render_member_row(client, member, is_self=member.email == session.email)


if __name__ == "__main__":
    main()
