"""Schemas for the tenant-admin escalations view (feature 007, US3).

Read-only. Tenant id is derived from the caller's verified JWT membership
(``AdminIdentityDep``) and is never accepted as a field.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class EscalationResponse(BaseModel):
    """One escalated conversation with its captured context."""

    conversation_id: UUID
    reason: str
    summary: str
    conversation_status: str
    created_at: datetime
    updated_at: datetime
