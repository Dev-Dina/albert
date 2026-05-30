"""Escalation lifecycle tests (feature 008).

Covers the pure two-state transition map: both directions allowed, same-state
(idempotent) allowed, and invalid values rejected. Mirrors the pure-map portion
of ``test_lead_lifecycle.py``.
"""

from __future__ import annotations

from app.services import escalation_lifecycle as lc


def test_status_validity() -> None:
    assert lc.is_valid_status("open")
    assert lc.is_valid_status("resolved")
    assert not lc.is_valid_status("frozen")
    assert not lc.is_valid_status("")
    assert lc.ESCALATION_STATUSES == ("open", "resolved")


def test_symmetric_transitions_allowed() -> None:
    assert lc.can_transition("open", "resolved")
    assert lc.can_transition("resolved", "open")


def test_idempotent_same_state_allowed() -> None:
    # Resolving an already-resolved escalation (or reopening an open one) is a
    # permitted no-op (FR-012).
    assert lc.can_transition("open", "open")
    assert lc.can_transition("resolved", "resolved")


def test_invalid_status_not_transitionable() -> None:
    assert not lc.can_transition("open", "frozen")
    assert not lc.can_transition("frozen", "open")
    assert lc.allowed_targets("frozen") == set()


def test_allowed_targets_from_valid_states() -> None:
    assert lc.allowed_targets("open") == {"open", "resolved"}
    assert lc.allowed_targets("resolved") == {"open", "resolved"}
