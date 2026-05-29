"""Load per-tenant runtime config for the live chat path (Phase 6.2B).

Surfaces the tenant's business name, agent persona, and tenant guardrail rails
so chat uses the tenant's own configuration instead of platform defaults:

  - ``business_name`` ← ``tenants.name``
  - ``persona``       ← ``widgets.theme.persona`` else ``widgets.name``
  - ``tenant_rails``  ← ``widget_guardrail_configs.config`` mapped into the
                        guardrails sidecar's TenantRails shape

All reads are tenant-scoped under the active RLS context (the caller opens the
session with ``app.current_tenant`` set). Tenant rails can only ADD restrictions;
the guardrails sidecar evaluates platform rules first, so a permissive tenant
config can never weaken the platform floor.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.tenant import Tenant
from app.repositories import guardrail_config_repo, widget_repo

logger = logging.getLogger(__name__)

_DEFAULT_PERSONA = "Albert"
_DEFAULT_BUSINESS = "the business"


@dataclass(frozen=True)
class TenantRuntimeConfig:
    business_name: str
    persona: str
    tenant_rails: dict[str, Any] | None


def _to_tenant_rails(config: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map the admin-edited guardrail config JSON into the sidecar TenantRails shape.

    The admin/floor config uses ``block_topics``; the guardrails sidecar reads
    ``blocked_topics`` — bridge the two (and accept aliases) so a tenant's
    configured blocks are actually enforced at runtime.
    """
    if not config:
        return None
    rails: dict[str, Any] = {}
    blocked = config.get("block_topics") or config.get("blocked_topics")
    allowed = config.get("allow_topics") or config.get("allowed_topics")
    tone = config.get("refusal_tone") or config.get("tone")
    tools = config.get("enabled_tools")
    if blocked:
        rails["blocked_topics"] = list(blocked)
    if allowed:
        rails["allowed_topics"] = list(allowed)
    if tone:
        rails["tone"] = tone
    if tools:
        rails["enabled_tools"] = list(tools)
    return rails or None


async def load_runtime_config(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    widget_id: uuid.UUID | None = None,
) -> TenantRuntimeConfig:
    """Return the tenant's business name, persona, and tenant rails.

    Fail-soft: this is optional enrichment, not a security control. If the read
    fails, fall back to platform defaults (persona "Albert", no tenant rails) so
    chat stays available — the platform guardrail floor is enforced independently
    of tenant rails, so dropping tenant rails never weakens platform protection.
    """
    try:
        name = (
            await db.execute(select(Tenant.name).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        business_name = name or _DEFAULT_BUSINESS

        persona = _DEFAULT_PERSONA
        if widget_id is not None:
            widget = await widget_repo.get_by_id(db, widget_id)
            if widget is not None:
                persona = (widget.theme or {}).get("persona") or widget.name or _DEFAULT_PERSONA

        row = await guardrail_config_repo.get_for_tenant(db, tenant_id)
        tenant_rails = _to_tenant_rails(row.config if row else None)

        return TenantRuntimeConfig(
            business_name=business_name,
            persona=persona,
            tenant_rails=tenant_rails,
        )
    except Exception:
        logger.warning("tenant_runtime.load_failed — using platform defaults")
        return TenantRuntimeConfig(
            business_name=_DEFAULT_BUSINESS, persona=_DEFAULT_PERSONA, tenant_rails=None
        )
