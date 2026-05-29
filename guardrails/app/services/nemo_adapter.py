"""NeMo Guardrails adapter — configurable tenant topical rails.

Runs NeMo Guardrails with **no LLM and no embeddings**: the tenant allowed/blocked
topic decision is made by a registered custom Python action (`check_topic_policy`)
that reuses the deterministic matcher in ``app.topic_policy``. The NeMo rails engine
is what executes the configurable topical/conversation policy (brief compliance).

Ordering invariant: deterministic PLATFORM deny rules run BEFORE this in
``app.rails`` and short-circuit, so NeMo can only ADD a tenant/topical block — it can
never weaken a platform deny. Redaction is separate. Never logs raw text or secrets.

Availability policy:
- Local dev (`APP_ENV` in {local,dev,test,...} and `GUARDRAILS_REQUIRE_NEMO` != "1"):
  if NeMo can't load, degrade gracefully (callers fall back to the deterministic
  matcher) — convenient for running unit tests without the heavy dependency.
- CI / production (the guardrails container sets `GUARDRAILS_REQUIRE_NEMO=1`):
  a NeMo load/eval failure **fails loud** — we never silently become
  deterministic-only while claiming NeMo compliance.
"""

from __future__ import annotations

import contextvars
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas import TenantRails
from app.topic_policy import match_tenant_topics

logger = logging.getLogger(__name__)

# guardrails/app/services/nemo_adapter.py -> parents[2] == guardrails/
_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "nemo"
_REFUSAL_MARKER = "__TENANT_TOPIC_BLOCKED__"
_DEV_ENVS = {"local", "dev", "development", "test", "testing", "ci-dev"}

# Per-call tenant rails, read by the custom action. ContextVar is asyncio-safe:
# set before generate_async, inherited by NeMo's action coroutine in the same task.
_current_rails: contextvars.ContextVar[TenantRails | None] = contextvars.ContextVar(
    "_current_rails", default=None
)


def _require_nemo() -> bool:
    """True when a missing/broken NeMo must fail loud (CI/prod), not degrade."""
    if os.getenv("GUARDRAILS_REQUIRE_NEMO", "0") == "1":
        return True
    return os.getenv("APP_ENV", "local").strip().lower() not in _DEV_ENVS


@dataclass(frozen=True)
class TopicVerdict:
    blocked: bool
    categories: list[str] = field(default_factory=list)


async def check_topic_policy(context: dict | None = None) -> bool:
    """NeMo custom action: deterministic tenant topic match (no LLM/embeddings)."""
    text = (context or {}).get("user_message") or ""
    rails = _current_rails.get()
    if rails is None:
        return False
    return bool(match_tenant_topics(text, rails))


_rails = None  # loaded LLMRails instance, or None
_load_error: Exception | None = None


def _load() -> None:
    global _rails, _load_error
    if _rails is not None or _load_error is not None:
        return
    try:
        from nemoguardrails import LLMRails, RailsConfig

        config = RailsConfig.from_path(str(_CONFIG_DIR))
        rails = LLMRails(config)
        rails.register_action(check_topic_policy, "check_topic_policy")
        _rails = rails
        logger.info("nemo.loaded config=%s", _CONFIG_DIR.name)
    except Exception as exc:  # noqa: BLE001 — broad by design; decide loud vs graceful
        _load_error = exc
        if _require_nemo():
            raise
        logger.warning("nemo.load_failed dev_fallback error=%s", type(exc).__name__)


_load()


def nemo_available() -> bool:
    """True iff the NeMo rails engine loaded. MUST be True in CI/prod."""
    return _rails is not None


async def evaluate_topic(text: str, tenant_rails: TenantRails | None) -> TopicVerdict | None:
    """Run NeMo tenant topical rails.

    Returns a ``TopicVerdict`` when NeMo ran, or ``None`` to signal the caller to
    fall back to the deterministic matcher (dev-only; raises in CI/prod).
    """
    if _rails is None:
        if _require_nemo():
            raise RuntimeError("NeMo guardrails required but unavailable")
        return None
    if tenant_rails is None:
        return TopicVerdict(blocked=False)

    token = _current_rails.set(tenant_rails)
    try:
        result = await _rails.generate_async(
            messages=[{"role": "user", "content": text}],
            options={"rails": ["input"]},
        )
    except Exception as exc:  # noqa: BLE001
        if _require_nemo():
            raise
        logger.warning("nemo.eval_failed dev_fallback error=%s", type(exc).__name__)
        return None
    finally:
        _current_rails.reset(token)

    content = ""
    response = getattr(result, "response", None)
    if response:
        content = (response[-1].get("content") or "").strip()
    blocked = content == _REFUSAL_MARKER
    categories = match_tenant_topics(text, tenant_rails) if blocked else []
    return TopicVerdict(blocked=blocked, categories=categories)
