"""Shared visual tokens for the Albert admin app.

Streamlit's built-in theme system is limited, so we layer a small CSS
sheet on top via ``inject_global_css()`` to enforce the minimalism +
bento design: tight section cards, a single primary CTA per page,
semantic state colors, and predictable spacing rhythm (4/8 scale).

Every page module imports ``apply_page_chrome()`` at the top — it sets
``st.set_page_config`` once and injects the CSS sheet.
"""

from __future__ import annotations

import streamlit as st

# --- Semantic color tokens (light theme) ----------------------------------
#
# Token names mirror the design-system roles used in the backend. Avoid
# referencing raw hex anywhere outside this module.
COLORS = {
    "primary": "#2563eb",       # blue-600
    "primary_hover": "#1d4ed8", # blue-700
    "secondary": "#475569",     # slate-600 — secondary intent (neutral action)
    "secondary_hover": "#334155", # slate-700
    "destructive": "#dc2626",   # red-600 — destructive intent (alias of danger)
    "destructive_hover": "#b91c1c", # red-700
    "surface": "#ffffff",
    "background": "#f8fafc",    # slate-50
    "hover_bg": "#f1f5f9",      # slate-100 — row hover
    "selected_bg": "#eff6ff",   # blue-50 — selected row
    "focus_ring": "#2563eb",    # blue-600 — visible focus outline
    "border": "#e2e8f0",        # slate-200
    "border_strong": "#cbd5e1", # slate-300
    "text_primary": "#0f172a",  # slate-900
    "text_secondary": "#475569",# slate-600
    "text_muted": "#94a3b8",    # slate-400
    "danger": "#dc2626",        # red-600
    "danger_bg": "#fef2f2",
    "warning": "#d97706",       # amber-600
    "warning_bg": "#fffbeb",
    "success": "#059669",       # emerald-600
    "success_bg": "#ecfdf5",
}

# Type scale (rem) — a single modular scale shared by both surfaces (FR-040).
TYPE_SCALE = {
    "display": "1.75rem",   # h1
    "title": "1.25rem",     # h2
    "subtitle": "1rem",     # h3
    "body": "0.9375rem",
    "meta": "0.875rem",
    "caption": "0.8125rem",
}

# Spacing scale (rem) on a 4 / 8 rhythm — referenced by component CSS below.
SPACING = {
    "xs": "0.25rem",
    "sm": "0.5rem",
    "md": "0.75rem",
    "lg": "1rem",
    "xl": "1.5rem",
    "2xl": "2rem",
}


_CSS = f"""
<style>
/* Tight bento layout — each block_container section becomes a card. */
section.main > div.block-container {{
  padding-top: 2rem;
  padding-bottom: 4rem;
  max-width: 1100px;
}}

h1, h2, h3 {{
  color: {COLORS['text_primary']};
  letter-spacing: -0.01em;
}}
h1 {{ font-size: 1.75rem; font-weight: 700; }}
h2 {{ font-size: 1.25rem; font-weight: 600; margin-top: 1.5rem; }}
h3 {{ font-size: 1rem;    font-weight: 600; }}

.albert-section {{
  background: {COLORS['surface']};
  border: 1px solid {COLORS['border']};
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  margin-bottom: 1rem;
}}
.albert-section + .albert-section {{ margin-top: 0.75rem; }}

.albert-meta {{
  color: {COLORS['text_secondary']};
  font-size: 0.875rem;
  line-height: 1.5;
}}
.albert-muted {{ color: {COLORS['text_muted']}; font-size: 0.8125rem; }}

.albert-badge {{
  display: inline-block;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
  letter-spacing: 0.02em;
  text-transform: uppercase;
}}
.albert-badge-success {{ color: {COLORS['success']}; background: {COLORS['success_bg']}; }}
.albert-badge-danger  {{ color: {COLORS['danger']};  background: {COLORS['danger_bg']}; }}
.albert-badge-warning {{ color: {COLORS['warning']}; background: {COLORS['warning_bg']}; }}
.albert-badge-muted   {{ color: {COLORS['text_secondary']}; background: {COLORS['background']}; border: 1px solid {COLORS['border']}; }}

.albert-callout {{
  border: 1px solid {COLORS['warning']};
  background: {COLORS['warning_bg']};
  color: #78350f;
  border-radius: 10px;
  padding: 0.875rem 1rem;
  font-size: 0.9375rem;
}}
.albert-callout-danger {{ border-color: {COLORS['danger']}; background: {COLORS['danger_bg']}; color: #7f1d1d; }}
.albert-callout-info   {{ border-color: {COLORS['border_strong']}; background: {COLORS['background']}; color: {COLORS['text_secondary']}; }}

/* Primary action button — only one per page (visually) */
div.stButton > button[kind="primary"] {{
  background: {COLORS['primary']};
  border-color: {COLORS['primary']};
  font-weight: 600;
  border-radius: 8px;
}}
div.stButton > button[kind="primary"]:hover {{
  background: {COLORS['primary_hover']};
  border-color: {COLORS['primary_hover']};
}}

/* Tabular figures for versions / counts / timestamps */
.albert-mono {{
  font-variant-numeric: tabular-nums;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.875rem;
}}

/* --- Focus ring (FR-047): visible on every interactive element --------- */
button:focus-visible,
a:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible,
[role="button"]:focus-visible,
div.stButton > button:focus-visible {{
  outline: 2px solid {COLORS['focus_ring']} !important;
  outline-offset: 2px !important;
  border-radius: 8px;
}}

/* --- Secondary / destructive button intents (FR-040) ------------------- */
.albert-intent-secondary div.stButton > button {{
  background: {COLORS['surface']};
  color: {COLORS['secondary']};
  border: 1px solid {COLORS['border_strong']};
  font-weight: 600;
  border-radius: 8px;
}}
.albert-intent-secondary div.stButton > button:hover {{
  background: {COLORS['hover_bg']};
  border-color: {COLORS['secondary_hover']};
  color: {COLORS['secondary_hover']};
}}
.albert-intent-destructive div.stButton > button {{
  background: {COLORS['destructive']};
  border-color: {COLORS['destructive']};
  color: #ffffff;
  font-weight: 600;
  border-radius: 8px;
}}
.albert-intent-destructive div.stButton > button:hover {{
  background: {COLORS['destructive_hover']};
  border-color: {COLORS['destructive_hover']};
}}

/* --- Bento grid + card (FR-041) ---------------------------------------- */
.albert-card {{
  background: {COLORS['surface']};
  border: 1px solid {COLORS['border']};
  border-radius: 12px;
  padding: 1.25rem 1.5rem;
  height: 100%;
}}
.albert-card-metric {{
  font-variant-numeric: tabular-nums;
  font-size: 2rem;
  font-weight: 700;
  color: {COLORS['text_primary']};
  line-height: 1.1;
}}
.albert-card-label {{
  font-size: {TYPE_SCALE['caption']};
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: {COLORS['text_muted']};
  margin-bottom: 0.25rem;
}}

/* --- Data table: sticky header, row hover, selected (FR-046) ----------- */
.albert-table-wrap {{
  border: 1px solid {COLORS['border']};
  border-radius: 12px;
  overflow: auto;
  max-height: 70vh;
}}
table.albert-table {{
  width: 100%;
  border-collapse: collapse;
  font-size: {TYPE_SCALE['meta']};
}}
table.albert-table thead th {{
  position: sticky;
  top: 0;
  background: {COLORS['background']};
  color: {COLORS['text_secondary']};
  text-align: left;
  font-weight: 600;
  padding: 0.625rem 0.875rem;
  border-bottom: 1px solid {COLORS['border']};
  z-index: 1;
}}
table.albert-table tbody td {{
  padding: 0.625rem 0.875rem;
  border-bottom: 1px solid {COLORS['border']};
  color: {COLORS['text_primary']};
}}
table.albert-table tbody tr:hover {{ background: {COLORS['hover_bg']}; }}
table.albert-table tbody tr.is-selected {{ background: {COLORS['selected_bg']}; }}

/* --- Sparkline (FR-015 cost overview) ---------------------------------- */
.albert-sparkline {{ display: inline-block; vertical-align: middle; }}
.albert-sparkline polyline {{ fill: none; stroke: {COLORS['primary']}; stroke-width: 1.5; }}
.albert-sparkline .albert-sparkline-area {{ fill: {COLORS['selected_bg']}; stroke: none; }}

/* --- Timeline (FR-016 audit log) --------------------------------------- */
.albert-timeline {{ list-style: none; margin: 0; padding: 0; }}
.albert-timeline-item {{
  position: relative;
  padding: 0 0 1rem 1.25rem;
  border-left: 2px solid {COLORS['border']};
}}
.albert-timeline-item::before {{
  content: "";
  position: absolute;
  left: -5px;
  top: 0.25rem;
  width: 8px;
  height: 8px;
  border-radius: 9999px;
  background: {COLORS['primary']};
}}
.albert-timeline-item:last-child {{ border-left-color: transparent; }}
.albert-timeline-meta {{ color: {COLORS['text_muted']}; font-size: {TYPE_SCALE['caption']}; }}

/* --- Code block (FR-021 embed snippet; Pygments writes .highlight) ----- */
.albert-codeblock, .albert-codeblock .highlight {{
  background: #0f172a;
  border-radius: 10px;
  padding: 1rem 1.125rem;
  overflow: auto;
}}
.albert-codeblock pre, .albert-codeblock code {{
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: {TYPE_SCALE['caption']};
  color: #e2e8f0;
  margin: 0;
}}

/* --- Empty / loading / error states (FR-042–FR-044) -------------------- */
.albert-empty {{
  text-align: center;
  padding: 2.5rem 1.5rem;
  color: {COLORS['text_secondary']};
  border: 1px dashed {COLORS['border_strong']};
  border-radius: 12px;
  background: {COLORS['background']};
}}
.albert-empty-icon {{ font-size: 1.75rem; opacity: 0.6; }}
.albert-skeleton {{
  background: linear-gradient(90deg, {COLORS['background']} 25%, {COLORS['hover_bg']} 37%, {COLORS['background']} 63%);
  background-size: 400% 100%;
  animation: albert-shimmer 1.4s ease infinite;
  border-radius: 8px;
  height: 1rem;
  margin: 0.5rem 0;
}}
@keyframes albert-shimmer {{
  0% {{ background-position: 100% 50%; }}
  100% {{ background-position: 0 50%; }}
}}
</style>
"""


def apply_page_chrome(title: str, *, icon: str = "🟦") -> None:
    """Set page config + inject the shared stylesheet.

    Call once at the top of every page module. ``st.set_page_config`` is
    idempotent within a single Streamlit run, so reapplying is cheap.
    """
    st.set_page_config(
        page_title=f"Albert · {title}",
        page_icon=icon,
        layout="wide",
        initial_sidebar_state="expanded",
        menu_items={
            "About": "Albert tenant admin — manage widgets, origins, and guardrails.",
        },
    )
    st.markdown(_CSS, unsafe_allow_html=True)


def section(label: str) -> None:
    """Render a bento section heading. Inline so callers stay terse."""
    st.markdown(f"<h2>{label}</h2>", unsafe_allow_html=True)


def callout(message: str, *, level: str = "info") -> None:
    """Render a callout banner. ``level`` ∈ {info, warning, danger}."""
    cls = {
        "info": "albert-callout-info",
        "warning": "",
        "danger": "albert-callout-danger",
    }.get(level, "albert-callout-info")
    st.markdown(
        f'<div class="albert-callout {cls}">{message}</div>',
        unsafe_allow_html=True,
    )


def status_badge(value: str) -> str:
    """Return the HTML for a status pill given a widget status string."""
    cls = {
        "enabled": "albert-badge-success",
        "disabled": "albert-badge-danger",
    }.get(value, "albert-badge-muted")
    return f'<span class="albert-badge {cls}">{value}</span>'
