"""Schema for the cross-tenant audit endpoint (FR-050 exception 3).

The field set here is the content-exclusion allowlist for
``GET /tenants/audit``: audit metadata only — actor, action, target tenant,
timestamp, and structured ``meta``. It MUST NOT carry any conversation,
message, lead, or CMS content. ``test_tenants_audit_cross_tenant.py``
asserts the response JSON keys stay within this set.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    entry_id: UUID
    actor_user_id: UUID | None
    actor_email: str | None
    action: str
    target_tenant_id: UUID | None
    target_tenant_slug: str | None
    created_at: datetime
    meta: dict[str, Any]
