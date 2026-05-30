"""Escalation lifecycle state machine (feature 008).

Authoritative transition rules for an escalation's ``status``. Kept as a pure
module (mirrors ``lead_lifecycle.py``) so the rules can be unit-tested in
isolation and reused by the service layer.

Unlike the lead lifecycle (strict-forward, terminal states), the escalation
lifecycle is a **symmetric two-state** machine and every transition between the
two valid states is permitted, including a no-op to the current state
(idempotency, FR-012):

    open      <-> resolved
    open      ->  open       (idempotent no-op)
    resolved  ->  resolved   (idempotent; refreshes resolved_at/resolved_by)

Consequently there is no "disallowed transition" path here — the only rejection
is an *invalid status value*, which is caught upstream by the Pydantic enum (422)
and re-checked by ``is_valid_status``.
"""

from __future__ import annotations

# Canonical set of valid escalation statuses.
ESCALATION_STATUSES: tuple[str, ...] = ("open", "resolved")


def is_valid_status(status: str) -> bool:
    return status in ESCALATION_STATUSES


def allowed_targets(current: str) -> set[str]:
    """Statuses ``current`` may transition to.

    Every valid status is reachable from any valid status (symmetric +
    idempotent). Returns an empty set if ``current`` is not a valid status.
    """
    if not is_valid_status(current):
        return set()
    return set(ESCALATION_STATUSES)


def can_transition(current: str, target: str) -> bool:
    """True iff moving from ``current`` to ``target`` is permitted.

    Requires both to be valid statuses; all such transitions (including
    same-state) are allowed.
    """
    return is_valid_status(current) and target in allowed_targets(current)
