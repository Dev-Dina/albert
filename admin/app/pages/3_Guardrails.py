"""Guardrails page — view + edit tenant guardrail config (floor-enforced).

The admin can strengthen any setting (e.g. add to ``block_topics``, raise
``injection_defenses.level`` from ``balanced`` to ``strict``) but never
weaken below the platform floor. A floor violation returns HTTP 422 with
``{key_path, attempted_value, floor_value}`` — we render that inline so
the admin sees exactly which key broke the floor.
"""

from __future__ import annotations

import json

import streamlit as st

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
    FloorViolationError,
)
from app.lib.auth import clear_session, render_sidebar_account, require_session
from app.lib.theme import apply_page_chrome, callout, section


_HELP_TEXT = (
    "Tenant guardrail config is a JSON object. You can ADD or STRENGTHEN any "
    "setting, but cannot weaken anything below the platform floor. "
    "Booleans floored at true cannot be set to false; lists floored with "
    "items must keep all those items; injection_defenses.level can only go "
    "up (basic → balanced → strict)."
)


def main() -> None:
    apply_page_chrome("Guardrails", icon="🧱")
    client = BackendClient()
    session = require_session(client)
    client.token = session.token
    render_sidebar_account(session)

    st.markdown("<h1>Guardrails</h1>", unsafe_allow_html=True)
    st.markdown(
        f'<p class="albert-meta">{_HELP_TEXT}</p>',
        unsafe_allow_html=True,
    )

    try:
        current = client.get_guardrail_config()
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return
    except BackendError as exc:
        callout(f"Could not load guardrail config: {exc}", level="danger")
        return

    section("Current config")
    st.code(
        json.dumps(current, indent=2) if current else "{}",
        language="json",
    )

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
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return
    except BackendError as exc:
        callout(f"Could not save config: {exc}", level="danger")
        return

    st.success("Guardrail config saved.")
    st.rerun()


if __name__ == "__main__":
    main()
