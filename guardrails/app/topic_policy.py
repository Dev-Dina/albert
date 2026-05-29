"""Deterministic tenant topical-policy matcher.

Shared by the deterministic fallback in ``rails.py`` and the NeMo custom action in
``services/nemo_adapter.py`` so both agree on allowed/blocked-topic decisions.
Pure and side-effect-free; never logs.
"""

from __future__ import annotations

from app.schemas import TenantRails


def match_tenant_topics(text: str, tenant_rails: TenantRails | None) -> list[str]:
    """Return tenant topic-policy categories triggered by ``text`` (empty = allowed).

    - ``tenant_blocked_topic``: text mentions a tenant-blocked topic.
    - ``tenant_allowed_topics``: an allow-list is set and text matches none of it.
    """
    if tenant_rails is None:
        return []
    lowered = text.lower()
    categories: list[str] = []
    for topic in tenant_rails.blocked_topics:
        normalized = topic.strip().lower()
        if normalized and normalized in lowered:
            categories.append("tenant_blocked_topic")
            break
    if tenant_rails.allowed_topics:
        allowed = [t.strip().lower() for t in tenant_rails.allowed_topics if t.strip()]
        if allowed and not any(t in lowered for t in allowed):
            categories.append("tenant_allowed_topics")
    return categories
