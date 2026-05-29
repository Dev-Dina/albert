"""Shared design-system UI primitives for both role surfaces (FR-040–FR-047).

Every page in ``pages_platform/`` and ``pages_tenant/`` composes its surface
from these primitives so the two roles stay visually identical without
coupling their page logic. The visual tokens / CSS class hooks these emit are
defined in :mod:`app.lib.theme` (``apply_page_chrome`` injects the sheet).

Primitives:
  * ``card`` / ``bento_grid`` — bento landing cards (FR-041)
  * ``data_table`` — sticky-header table with hover + selected row (FR-046)
  * ``sparkline`` — inline SVG trend (FR-015); returns HTML for table cells
  * ``timeline`` — vertical newest-first event list (FR-016)
  * ``code_block`` — Pygments syntax-highlighted block (FR-021)
  * ``empty_state`` / ``loading_skeleton`` / ``error_state`` (FR-042–FR-044)
  * ``destructive_confirm`` — typed-slug confirmation gate (FR-013)
  * ``inline_validated_input`` — validate-before-submit field (FR-045)
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable, Sequence
from typing import Any

import streamlit as st

from app.lib.theme import callout


def _esc(value: Any) -> str:
    return html.escape("" if value is None else str(value))


# --- Bento cards (FR-041) --------------------------------------------------


def card(
    *,
    label: str,
    value: Any,
    secondary: str | None = None,
    value_is_html: bool = False,
) -> None:
    """Render one bento card: an uppercase label, a big metric, a sub-line."""
    value_html = str(value) if value_is_html else _esc(value)
    secondary_html = (
        f'<div class="albert-meta">{_esc(secondary)}</div>' if secondary else ""
    )
    st.markdown(
        '<div class="albert-card">'
        f'<div class="albert-card-label">{_esc(label)}</div>'
        f'<div class="albert-card-metric">{value_html}</div>'
        f"{secondary_html}</div>",
        unsafe_allow_html=True,
    )


def bento_grid(cards: Sequence[dict[str, Any]], *, columns: int | None = None) -> None:
    """Lay out a row of :func:`card` specs. Each spec is a kwargs dict."""
    if not cards:
        return
    count = columns or min(len(cards), 4)
    cols = st.columns(count, gap="medium")
    for index, spec in enumerate(cards):
        with cols[index % count]:
            card(**spec)


# --- Data table (FR-046) ---------------------------------------------------


def data_table(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    selected_row: int | None = None,
    raw_cols: Iterable[int] = (),
) -> None:
    """Render a sticky-header HTML table with hover + selected-row styling.

    Cell values are HTML-escaped unless their column index is in ``raw_cols``
    (used for pre-rendered cells like status badges or :func:`sparkline`).
    """
    raw = set(raw_cols)
    head = "".join(f"<th>{_esc(col)}</th>" for col in columns)
    body: list[str] = []
    for index, row in enumerate(rows):
        row_cls = ' class="is-selected"' if selected_row == index else ""
        cells = "".join(
            f"<td>{cell if col_index in raw else _esc(cell)}</td>"
            for col_index, cell in enumerate(row)
        )
        body.append(f"<tr{row_cls}>{cells}</tr>")
    st.markdown(
        '<div class="albert-table-wrap"><table class="albert-table">'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody>"
        "</table></div>",
        unsafe_allow_html=True,
    )


# --- Sparkline (FR-015) ----------------------------------------------------


def sparkline(
    samples: Sequence[float], *, width: int = 120, height: int = 28, area: bool = True
) -> str:
    """Return an inline SVG sparkline as an HTML string (embeddable in a cell)."""
    points = [float(value) for value in samples]
    if not points:
        return '<span class="albert-muted">—</span>'
    low, high = min(points), max(points)
    span = (high - low) or 1.0
    n = len(points)
    step = width / (n - 1) if n > 1 else float(width)
    coords = [
        (i * step, height - ((value - low) / span) * (height - 2) - 1)
        for i, value in enumerate(points)
    ]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    area_poly = ""
    if area and n > 1:
        area_poly = (
            f'<polyline class="albert-sparkline-area" '
            f'points="0,{height} {line} {width},{height}"/>'
        )
    return (
        f'<svg class="albert-sparkline" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
        f'{area_poly}<polyline points="{line}"/></svg>'
    )


# --- Timeline (FR-016) -----------------------------------------------------


def timeline(items: Sequence[dict[str, str]]) -> None:
    """Render a newest-first vertical timeline.

    Each item is a dict with ``title`` (bold line), ``meta`` (muted footer),
    and optional ``body``.
    """
    if not items:
        empty_state(
            "No activity yet",
            description="Events will appear here as they happen.",
            icon="🕓",
        )
        return
    entries: list[str] = []
    for item in items:
        body = item.get("body")
        body_html = f'<div class="albert-meta">{_esc(body)}</div>' if body else ""
        entries.append(
            '<li class="albert-timeline-item">'
            f"<div><strong>{_esc(item.get('title'))}</strong></div>"
            f"{body_html}"
            f'<div class="albert-timeline-meta">{_esc(item.get("meta"))}</div></li>'
        )
    st.markdown(
        f'<ul class="albert-timeline">{"".join(entries)}</ul>',
        unsafe_allow_html=True,
    )


# --- Code block (FR-021) ---------------------------------------------------


def code_block(code: str, *, language: str = "html") -> None:
    """Render a syntax-highlighted code block using Pygments.

    Falls back to ``st.code`` if Pygments or the lexer is unavailable, so the
    snippet is always shown.
    """
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name

        lexer = get_lexer_by_name(language)
        # noclasses=True inlines the styles so no extra stylesheet is needed.
        formatter = HtmlFormatter(noclasses=True, style="monokai", nowrap=False)
        inner = highlight(code, lexer, formatter)
        st.markdown(
            f'<div class="albert-codeblock">{inner}</div>', unsafe_allow_html=True
        )
    except Exception:  # pragma: no cover - defensive fallback
        st.code(code, language=language)


# --- Empty / loading / error states (FR-042–FR-044) ------------------------


def empty_state(title: str, *, description: str | None = None, icon: str = "📭") -> None:
    """Render a designed empty state (never a blank page)."""
    description_html = (
        f'<div class="albert-meta">{_esc(description)}</div>' if description else ""
    )
    st.markdown(
        '<div class="albert-empty">'
        f'<div class="albert-empty-icon">{icon}</div>'
        f'<div style="font-weight:600;margin:0.5rem 0 0.25rem;">{_esc(title)}</div>'
        f"{description_html}</div>",
        unsafe_allow_html=True,
    )


def loading_skeleton(lines: int = 3, *, widths: Sequence[str] | None = None) -> None:
    """Render shimmer placeholder bars while data loads."""
    widths = widths or ("100%", "92%", "78%")
    bars = "".join(
        f'<div class="albert-skeleton" style="width:{widths[i % len(widths)]};"></div>'
        for i in range(lines)
    )
    st.markdown(bars, unsafe_allow_html=True)


def error_state(
    message: str, *, retry_label: str = "Retry", key: str = "albert-retry"
) -> bool:
    """Render an error banner with a retry button. Returns True if retry clicked."""
    callout(message, level="danger")
    return st.button(retry_label, key=key)


# --- Destructive confirmation (FR-013) -------------------------------------


def destructive_confirm(
    *,
    action_label: str,
    target: str,
    key: str,
    confirm_phrase: str | None = None,
    prompt: str | None = None,
) -> bool:
    """Typed-slug confirmation gate for destructive lifecycle actions.

    The confirm button stays disabled until the typed value matches the target
    phrase verbatim, and re-disables automatically on any edit (each rerun
    recomputes the match). Returns True only on a confirmed click.
    """
    phrase = confirm_phrase or target
    st.markdown(
        f'<div class="albert-callout albert-callout-danger">'
        f"{_esc(prompt) if prompt else 'This action cannot be undone.'} "
        f"Type <strong>{_esc(phrase)}</strong> to confirm.</div>",
        unsafe_allow_html=True,
    )
    typed = st.text_input(
        f"Type '{phrase}' to confirm",
        key=f"{key}__confirm_input",
        label_visibility="collapsed",
    )
    matches = typed.strip() == phrase
    st.markdown('<div class="albert-intent-destructive">', unsafe_allow_html=True)
    clicked = st.button(
        action_label,
        key=f"{key}__confirm_btn",
        disabled=not matches,
        type="primary",
    )
    st.markdown("</div>", unsafe_allow_html=True)
    return clicked and matches


# --- Inline-validated input (FR-045) ---------------------------------------


def inline_validated_input(
    label: str,
    *,
    validator: Callable[[str], str | None],
    key: str,
    password: bool = False,
    placeholder: str | None = None,
    help: str | None = None,
) -> tuple[str, bool]:
    """Text input that validates locally before any backend call.

    ``validator`` returns an error message for an invalid value or ``None`` when
    valid. An inline error is shown for non-empty invalid input. Returns
    ``(value, is_valid)``; ``is_valid`` is False for empty input.
    """
    value = st.text_input(
        label,
        key=key,
        type="password" if password else "default",
        placeholder=placeholder or "",
        help=help,
    )
    error = validator(value) if value else None
    if error:
        st.markdown(
            f'<div class="albert-callout albert-callout-danger">{_esc(error)}</div>',
            unsafe_allow_html=True,
        )
    return value, (value != "" and error is None)
