"""Guardrails page — view + edit tenant guardrail config (floor-enforced).

Migrated from ``pages/3_Guardrails.py`` to the ``st.navigation`` model. The
admin can strengthen any setting but never weaken below the platform floor; a
floor violation returns HTTP 422 with ``{key_path, attempted_value,
floor_value}`` and is rendered inline via ``FloorViolationError`` (SC-010).
"""

from __future__ import annotations

import json

import streamlit as st

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    FloorViolationError,
)
from app.lib import ui
from app.lib.auth import handle_backend_error, page_session
from app.lib.theme import callout, section


_HELP_TEXT = (
    "Tenant guardrail config is a JSON object. You can ADD or STRENGTHEN any "
    "setting, but cannot weaken anything below the platform floor. "
    "Booleans floored at true cannot be set to false; lists floored with "
    "items must keep all those items; injection_defenses.level can only go "
    "up (basic → balanced → strict)."
)


def main() -> None:
    session = page_session()
    client = BackendClient(token=session.token)

    st.markdown("<h1>Guardrails</h1>", unsafe_allow_html=True)
    st.markdown(f'<p class="albert-meta">{_HELP_TEXT}</p>', unsafe_allow_html=True)

    slot = st.empty()
    with slot.container():
        ui.loading_skeleton(3)

    try:
        current = client.get_guardrail_config()
    except BackendError as exc:
        slot.empty()
        if handle_backend_error(exc):
            return
        if ui.error_state(f"Could not load guardrail config: {exc}", key="guardrails-retry"):
            st.rerun()
        return

    slot.empty()

    section("Current config")
    st.code(json.dumps(current, indent=2) if current else "{}", language="json")

    section("Update config")
    with st.form("guardrail-edit", clear_on_submit=False):
        new_json = st.text_area(
            "Config (JSON object)",
            value=json.dumps(current, indent=2) if current else "{}",
            height=320,
        )
        submit = st.form_submit_button("Save config", type="primary")

    if not submit:
        return

    try:
        parsed = json.loads(new_json) if new_json.strip() else {}
        if not isinstance(parsed, dict):
            raise ValueError("Config must be a JSON object.")
    except ValueError as exc:
        callout(f"Invalid JSON: {exc}", level="danger")
        return

    try:
        client.put_guardrail_config(parsed)
    except FloorViolationError as exc:
        callout(
            (
                f"<strong>Floor violation</strong> at "
                f"<code>{exc.key_path}</code>: this tenant cannot weaken the "
                f"platform setting. Attempted <code>{exc.attempted_value!r}</code>, "
                f"floor is <code>{exc.floor_value!r}</code>."
            ),
            level="danger",
        )
        return
    except BackendError as exc:
        if handle_backend_error(exc):
            return
        callout(f"Could not save config: {exc}", level="danger")
        return

    st.success("Guardrail config saved.")
    st.rerun()


if __name__ == "__main__":
    main()
