"""Load CI gate thresholds from eval_thresholds.yaml at the repo root.

Single source of truth for every gate runner under evals/. Raises a clear
error if the file is missing or a required key is absent — gates MUST NOT
silently fall back to a default threshold.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


def _repo_root() -> Path:
    """Walk up from this file to the repo root (the dir containing eval_thresholds.yaml)."""
    here = Path(__file__).resolve()
    for parent in (here, *here.parents):
        if (parent / "eval_thresholds.yaml").exists():
            return parent
    raise FileNotFoundError(
        "Could not locate eval_thresholds.yaml from " f"{here}; expected at repo root."
    )


@lru_cache(maxsize=1)
def load_thresholds() -> dict[str, Any]:
    """Return the parsed eval_thresholds.yaml contents."""
    path = _repo_root() / "eval_thresholds.yaml"
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path} did not parse as a mapping; got {type(data).__name__}")
    return data


def get(*key_path: str) -> Any:
    """Look up a nested key (e.g. get('classifier', 'macro_f1_min'))."""
    node: Any = load_thresholds()
    for key in key_path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError("missing threshold key: " + ".".join(key_path))
        node = node[key]
    return node
