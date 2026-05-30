"""Schemas for the tenant-admin leads + members endpoints (FR-050 exception 1).

Source of truth: ``contracts/backend_additions_contract.md`` §§2–5. Every shape
here is tenant-admin-scoped; the tenant id is derived from the caller's verified
JWT membership and is NEVER accepted as a field on any of these models.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class LeadStatus(str, Enum):
    """Valid lead lifecycle statuses (feature 007, US2). Mirrors
    ``app.services.lead_lifecycle.LEAD_STATUSES``."""

    new = "new"
    contacted = "contacted"
    qualified = "qualified"
    won = "won"
    lost = "lost"


class LeadResponse(BaseModel):
    """One row of ``GET /api/v1/admin/leads`` (§2)."""

    id: UUID
    name: str
    contact: str
    intent: str
    status: str
    status_changed_at: datetime | None = None
    created_at: datetime
    conversation_id: UUID | None = None


class LeadStatusUpdateRequest(BaseModel):
    """Body of ``PATCH /api/v1/admin/leads/{lead_id}`` (feature 007, US2)."""

    status: LeadStatus


class MemberResponse(BaseModel):
    """One ``role='member'`` membership row (§3); also the 201 body of POST (§4)."""

    user_id: UUID
    email: str
    created_at: datetime


class MemberInviteRequest(BaseModel):
    """Body of ``POST /api/v1/admin/members`` (§4).

    ``password`` carries a server-side minimum length so a weak password is
    rejected with 422 before any write (mirrors the add-admin flow; no email
    invitation service is in scope).
    """

    email: EmailStr
    password: str = Field(min_length=8)


class MemberRemoveResponse(BaseModel):
    """200 body of ``DELETE /api/v1/admin/members/{user_id}`` (§5)."""

    tenant_id: UUID
    removed_user_id: UUID
