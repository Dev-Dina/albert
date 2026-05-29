"""WCAG-AA color-contrast audit helpers (T052, FR-048, SC-006).

Two pure functions implement the WCAG 2.1 §1.4.3 luminance / contrast-ratio
math (``relative_luminance`` and ``contrast_ratio``), plus ``audit_palette``
which runs the canonical list of foreground/background pairs the design system
actually renders (from :mod:`app.lib.theme`) and reports pass/fail against the
AA thresholds. No Streamlit / I/O — safe to unit-test directly.

Thresholds (WCAG 2.1 §1.4.3 / §1.4.11):
  * 4.5:1 — normal body text and status text.
  * 3.0:1 — large text (≥ 18pt / 14pt bold) and non-text UI components
    (focus rings, control boundaries).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.lib.theme import COLORS

# WCAG 2.1 AA minimum contrast ratios.
AA_NORMAL = 4.5
AA_LARGE = 3.0

# The palette pairs the design system actually paints, classified by the
# minimum AA ratio that applies to that role. Each tuple is
# ``(label, foreground_token, background_token, threshold)`` where the token
# names index :data:`app.lib.theme.COLORS`. (``surface`` is ``#ffffff`` and
# doubles as the white button-label color.)
AUDITED_PAIRS: tuple[tuple[str, str, str, float], ...] = (
    # --- Body / meta / caption text (FR-048) ------------------------------
    ("Body text on card", "text_primary", "surface", AA_NORMAL),
    ("Body text on page", "text_primary", "background", AA_NORMAL),
    ("Meta text on card", "text_secondary", "surface", AA_NORMAL),
    ("Meta text on page", "text_secondary", "background", AA_NORMAL),
    ("Muted caption on card", "text_muted", "surface", AA_NORMAL),
    ("Muted caption on page", "text_muted", "background", AA_NORMAL),
    # --- Interactive text -------------------------------------------------
    ("Link / accent text on card", "primary", "surface", AA_NORMAL),
    ("Secondary button text on card", "secondary", "surface", AA_NORMAL),
    ("Primary button label", "surface", "primary", AA_NORMAL),
    ("Destructive button label", "surface", "destructive", AA_NORMAL),
    # --- Status badge / pill text ----------------------------------------
    ("Success badge text", "success", "success_bg", AA_NORMAL),
    ("Danger badge text", "danger", "danger_bg", AA_NORMAL),
    ("Warning badge text", "warning", "warning_bg", AA_NORMAL),
    # --- Non-text UI components (FR-047 focus ring) ----------------------
    ("Focus ring on card", "focus_ring", "surface", AA_LARGE),
    ("Focus ring on page", "focus_ring", "background", AA_LARGE),
)


@dataclass(frozen=True)
class ContrastResult:
    """One audited foreground/background pair and its measured ratio."""

    label: str
    fg: str
    bg: str
    ratio: float
    threshold: float

    @property
    def passes(self) -> bool:
        return self.ratio >= self.threshold


def _to_rgb(color: str) -> tuple[int, int, int]:
    """Parse a ``#rgb`` or ``#rrggbb`` hex string into an (r, g, b) triple."""
    value = color.lstrip("#")
    if len(value) == 3:
        value = "".join(channel * 2 for channel in value)
    if len(value) != 6:
        raise ValueError(f"expected a hex color, got {color!r}")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _linearize(channel: int) -> float:
    """Convert an 8-bit sRGB channel to linear light (WCAG 2.1 §1.4.3)."""
    c = channel / 255.0
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str) -> float:
    """Relative luminance of a hex color per WCAG 2.1 §1.4.3."""
    r, g, b = (_linearize(channel) for channel in _to_rgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: str, bg: str) -> float:
    """Contrast ratio between two hex colors (1.0 … 21.0), order-independent."""
    lighter = relative_luminance(fg)
    darker = relative_luminance(bg)
    if darker > lighter:
        lighter, darker = darker, lighter
    return (lighter + 0.05) / (darker + 0.05)


def audit_palette(
    tokens: dict[str, str] | None = None,
    pairs: Iterable[tuple[str, str, str, float]] = AUDITED_PAIRS,
) -> list[ContrastResult]:
    """Return a WCAG-AA contrast report over the design-system palette pairs.

    ``tokens`` defaults to the live :data:`app.lib.theme.COLORS` palette so the
    audit always tracks what the app actually ships.
    """
    palette = tokens if tokens is not None else COLORS
    results: list[ContrastResult] = []
    for label, fg_key, bg_key, threshold in pairs:
        fg, bg = palette[fg_key], palette[bg_key]
        results.append(
            ContrastResult(
                label=label,
                fg=fg,
                bg=bg,
                ratio=round(contrast_ratio(fg, bg), 2),
                threshold=threshold,
            )
        )
    return results


def failures(results: Sequence[ContrastResult]) -> list[ContrastResult]:
    """Filter an audit report down to the pairs that miss their threshold."""
    return [result for result in results if not result.passes]
