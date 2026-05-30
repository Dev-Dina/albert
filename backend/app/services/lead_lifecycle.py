"""Lead lifecycle state machine (feature 007, US2).

Authoritative transition rules for lead status. Kept as a pure module so the
rules can be unit-tested in isolation and reused by the service layer. The
lifecycle is strict-forward with ``lost`` reachable from any non-terminal state;
``won`` and ``lost`` are terminal (FR-020).

    new       → contacted | lost
    contacted → qualified | lost
    qualified → won | lost
    won, lost → (terminal)
"""

from __future__ import annotations

# Canonical ordered set of valid lead statuses.
LEAD_STATUSES: tuple[str, ...] = ("new", "contacted", "qualified", "won", "lost")

_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "new": {"contacted", "lost"},
    "contacted": {"qualified", "lost"},
    "qualified": {"won", "lost"},
    "won": set(),
    "lost": set(),
}


def is_valid_status(status: str) -> bool:
    return status in LEAD_STATUSES


def allowed_targets(current: str) -> set[str]:
    """The set of statuses ``current`` may transition to (empty if terminal)."""
    return set(_ALLOWED_TRANSITIONS.get(current, set()))


def can_transition(current: str, target: str) -> bool:
    """True iff moving from ``current`` to ``target`` is permitted."""
    return target in _ALLOWED_TRANSITIONS.get(current, set())
