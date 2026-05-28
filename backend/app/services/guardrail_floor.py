"""Platform guardrail floor enforcement.

Loads ``guardrails/app/platform_floor.yaml`` once at startup and exposes
:func:`enforce_floor`, which compares a tenant-supplied guardrail config
against the floor and raises :class:`FloorViolation` if any value weakens
it. The error carries the key path + attempted + floor values so the admin
app can render a precise message (FR-019).
"""

from pathlib import Path
from typing import Any

import yaml

_FLOOR_PATH = (
    Path(__file__).resolve().parents[3] / "guardrails" / "app" / "platform_floor.yaml"
)

# Ordered defense levels for ``injection_defenses.level`` (lower index = weaker).
_INJECTION_LEVELS = ("basic", "balanced", "strict")


class FloorViolation(Exception):
    """A tenant config attempted to weaken the platform floor."""

    def __init__(self, key_path: str, attempted_value: Any, floor_value: Any) -> None:
        super().__init__(
            f"floor violation at {key_path}: attempted={attempted_value!r}, "
            f"floor={floor_value!r}"
        )
        self.key_path = key_path
        self.attempted_value = attempted_value
        self.floor_value = floor_value


def _load_floor() -> dict[str, Any]:
    if not _FLOOR_PATH.exists():
        return {}
    with _FLOOR_PATH.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{_FLOOR_PATH} must be a YAML mapping")
    return data


_floor_cache: dict[str, Any] | None = None


def get_floor() -> dict[str, Any]:
    """Return the cached platform floor mapping."""
    global _floor_cache
    if _floor_cache is None:
        _floor_cache = _load_floor()
    return _floor_cache


def _violation(key_path: str, attempted: Any, floor: Any) -> FloorViolation:
    return FloorViolation(key_path, attempted, floor)


def _check(path: str, floor_value: Any, tenant_value: Any) -> None:
    # Booleans: tenant must not flip a True floor to False.
    if isinstance(floor_value, bool):
        if tenant_value is None:
            # Missing on tenant side = inherit floor; not a weakening.
            return
        if not isinstance(tenant_value, bool):
            raise _violation(path, tenant_value, floor_value)
        if floor_value is True and tenant_value is False:
            raise _violation(path, tenant_value, floor_value)
        return

    # Lists (e.g. block_topics): tenant list must be a superset.
    if isinstance(floor_value, list):
        if tenant_value is None:
            return
        if not isinstance(tenant_value, list):
            raise _violation(path, tenant_value, floor_value)
        missing = [item for item in floor_value if item not in tenant_value]
        if missing:
            raise _violation(path, tenant_value, floor_value)
        return

    # Strings with ordered levels (special-case: injection_defenses.level).
    if path == "injection_defenses.level" and isinstance(floor_value, str):
        if tenant_value is None:
            return
        if tenant_value not in _INJECTION_LEVELS:
            raise _violation(path, tenant_value, floor_value)
        if _INJECTION_LEVELS.index(tenant_value) < _INJECTION_LEVELS.index(floor_value):
            raise _violation(path, tenant_value, floor_value)
        return

    # Nested mapping: recurse.
    if isinstance(floor_value, dict):
        if tenant_value is None:
            return
        if not isinstance(tenant_value, dict):
            raise _violation(path, tenant_value, floor_value)
        for sub_key, sub_floor in floor_value.items():
            sub_path = f"{path}.{sub_key}" if path else sub_key
            _check(sub_path, sub_floor, tenant_value.get(sub_key))
        return

    # Numeric: tenant must be >= floor (assumes "higher = stricter").
    if isinstance(floor_value, (int, float)):
        if tenant_value is None:
            return
        if not isinstance(tenant_value, (int, float)) or tenant_value < floor_value:
            raise _violation(path, tenant_value, floor_value)
        return

    # Fallback: exact-match required.
    if tenant_value is not None and tenant_value != floor_value:
        raise _violation(path, tenant_value, floor_value)


def enforce_floor(tenant_config: dict[str, Any]) -> None:
    """Raise :class:`FloorViolation` if ``tenant_config`` weakens the floor.

    A missing key on the tenant side means "inherit the floor" — never a
    violation. Tenant-only keys are ignored (tenants may add stricter rules).
    """
    floor = get_floor()
    for key, floor_value in floor.items():
        _check(key, floor_value, tenant_config.get(key))


def reload_floor() -> None:
    """Test hook: drop the cached floor so the next call re-reads the YAML."""
    global _floor_cache
    _floor_cache = None
