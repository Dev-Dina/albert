from uuid import UUID

from pydantic import BaseModel


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserResponse(BaseModel):
    id: str
    email: str
    role: str | None
    is_active: bool
    # FR-050 exception 2 — additive, optional, backward compatible. Populated
    # for tenant-scoped callers (tenant_admin/member); null for tenant_manager.
    tenant_id: UUID | None = None
    tenant_name: str | None = None
