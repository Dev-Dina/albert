"""WCAG-AA contrast audit tests (T053, FR-048, SC-006).

Pure-math tests over :mod:`app.lib.ui_audit`: the known reference ratios from
WCAG, then an assertion that every palette pair the design system actually
renders meets its AA threshold (4.5:1 body/status text, 3:1 large + UI). Per
``quickstart.md`` §3c, this test is the automated contrast gate.
"""

from __future__ import annotations

import pytest

from app.lib.ui_audit import (
    AUDITED_PAIRS,
    audit_palette,
    contrast_ratio,
    failures,
    relative_luminance,
)


def test_black_on_white_is_max_contrast() -> None:
    # WCAG defines pure black on pure white as the 21:1 maximum.
    assert contrast_ratio("#000000", "#ffffff") == pytest.approx(21.0, abs=0.01)


def test_identical_colors_have_no_contrast() -> None:
    assert contrast_ratio("#2563eb", "#2563eb") == pytest.approx(1.0, abs=0.001)


def test_contrast_is_symmetric() -> None:
    assert contrast_ratio("#0f172a", "#ffffff") == contrast_ratio("#ffffff", "#0f172a")


def test_relative_luminance_endpoints() -> None:
    assert relative_luminance("#000000") == pytest.approx(0.0, abs=1e-6)
    assert relative_luminance("#ffffff") == pytest.approx(1.0, abs=1e-6)


def test_shorthand_hex_is_accepted() -> None:
    assert contrast_ratio("#fff", "#000") == pytest.approx(21.0, abs=0.01)


def test_every_design_pair_meets_wcag_aa() -> None:
    report = audit_palette()
    bad = failures(report)
    detail = "\n".join(
        f"  {r.label}: {r.fg} on {r.bg} = {r.ratio}:1 (needs {r.threshold}:1)"
        for r in bad
    )
    assert not bad, f"palette pairs below WCAG AA:\n{detail}"


def test_audit_covers_every_declared_pair() -> None:
    # Guard against a pair silently dropping out of the report.
    assert len(audit_palette()) == len(AUDITED_PAIRS)


@pytest.mark.parametrize("result", audit_palette(), ids=lambda r: r.label)
def test_pair_passes(result) -> None:
    assert result.passes, (
        f"{result.label}: {result.fg} on {result.bg} = "
        f"{result.ratio}:1 < {result.threshold}:1"
    )
