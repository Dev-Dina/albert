"""Embed snippet page — per-widget copy-ready ``<script>`` line."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components

from app.clients.backend_client import (
    BackendClient,
    BackendError,
    BackendUnauthorizedError,
)
from app.lib.auth import clear_session, render_sidebar_account, require_session
from app.lib.theme import apply_page_chrome, callout, section


def _render_copy_button(snippet: str, key: str) -> None:
    """Tiny <button>+JS that copies the snippet using the Clipboard API."""
    # Snippet contains < and > — escape for safe HTML embedding inside <pre>.
    safe = (
        snippet.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
    # JSON-encode the snippet for embedding inside a <script> tag. The snippet
    # itself contains a literal "</script>" which would close the OUTER script
    # tag prematurely (browsers parse </script> in HTML context before JS
    # tokenisation). Escape "</" to "<\/" — same trick frameworks use for
    # inline JSON. Single backslash in the JS source via "\\/" Python literal.
    import json as _json
    encoded = _json.dumps(snippet).replace("</", "<\\/")
    html = f"""
    <style>
      .albert-snip-wrap {{ position: relative; }}
      .albert-snip-pre {{
        background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px;
        padding: 1rem 1.25rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
        font-size: 0.9375rem; color: #0f172a; white-space: pre-wrap; word-break: break-all;
      }}
      .albert-copy-btn {{
        position: absolute; top: 0.5rem; right: 0.5rem;
        background: #2563eb; color: white; border: none; padding: 0.375rem 0.75rem;
        border-radius: 6px; font-size: 0.8125rem; font-weight: 600; cursor: pointer;
      }}
      .albert-copy-btn:hover {{ background: #1d4ed8; }}
      .albert-copy-btn.copied {{ background: #059669; }}
    </style>
    <div class="albert-snip-wrap">
      <pre class="albert-snip-pre">{safe}</pre>
      <button id="copy-{key}" class="albert-copy-btn">Copy</button>
    </div>
    <script>
      (function() {{
        const btn = document.getElementById("copy-{key}");
        const text = {encoded};
        if (!btn) return;
        btn.addEventListener("click", async () => {{
          try {{
            await navigator.clipboard.writeText(text);
            btn.textContent = "Copied";
            btn.classList.add("copied");
            setTimeout(() => {{
              btn.textContent = "Copy";
              btn.classList.remove("copied");
            }}, 1500);
          }} catch (err) {{
            btn.textContent = "Press Ctrl+C";
          }}
        }});
      }})();
    </script>
    """
    components.html(html, height=170)


def main() -> None:
    apply_page_chrome("Embed snippet", icon="📋")
    client = BackendClient()
    session = require_session(client)
    client.token = session.token
    render_sidebar_account(session)

    st.markdown("<h1>Embed snippet</h1>", unsafe_allow_html=True)
    st.markdown(
        '<p class="albert-meta">Paste the snippet into your site\'s HTML, '
        "just before <code>&lt;/body&gt;</code>. Make sure the host origin "
        "is on your allowed-origins list.</p>",
        unsafe_allow_html=True,
    )

    try:
        widgets = client.list_widgets()
    except BackendUnauthorizedError:
        clear_session()
        st.rerun()
        return
    except BackendError as exc:
        callout(f"Could not load widgets: {exc}", level="danger")
        return

    if not widgets:
        callout(
            "You have no widgets yet. Create one from the Widgets page first.",
            level="info",
        )
        st.page_link("pages/1_Widgets.py", label="Go to Widgets", icon="🪟")
        return

    options = {f"{w.name}  ({w.public_widget_id})": w for w in widgets}
    label = st.selectbox("Choose widget", options=list(options.keys()))
    if label is None:
        return
    widget = options[label]

    try:
        snippet = client.get_embed_snippet(widget.id)
    except BackendError as exc:
        callout(f"Could not fetch snippet: {exc}", level="danger")
        return

    section("Copy-ready snippet")
    _render_copy_button(snippet.snippet, key=widget.id)

    section("Details")
    st.markdown(
        f'<div class="albert-meta">'
        f"<strong>Loader URL:</strong> <code>{snippet.loader_url}</code><br>"
        f"<strong>Widget id:</strong> <code>{snippet.data_widget_id}</code>"
        "</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
