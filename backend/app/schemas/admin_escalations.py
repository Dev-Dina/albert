"""Schemas for the tenant-admin escalations view (feature 007, US3).

Read-only. Tenant id is derived from the caller's verified JWT membership
(``AdminIdentityDep``) and is never accepted as a field.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class EscalationStatus(str, Enum):
    """Valid escalation lifecycle statuses (feature 008). Mirrors
    ``app.services.escalation_lifecycle.ESCALATION_STATUSES``."""

    open = "open"
    resolved = "resolved"


class EscalationResponse(BaseModel):
    """One escalated conversation with its captured context and resolve state."""

    conversation_id: UUID
    reason: str
    summary: str
    conversation_status: str
    status: str
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    created_at: datetime
    updated_at: datetime


class EscalationStatusUpdateRequest(BaseModel):
    """Body of ``PATCH /api/v1/admin/escalations/{conversation_id}`` (feature 008).

    The acting tenant and ``resolved_by`` user come from the verified admin
    membership (``AdminIdentityDep``); they are NEVER accepted as fields here.
    """

    status: EscalationStatus
