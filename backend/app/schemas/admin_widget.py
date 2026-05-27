"""Tenant-admin widget schemas.

All requests derive their tenant from the caller's membership; admin bodies
MUST NOT carry tenant_id either.
"""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    public_widget_id: str
    name: str
    theme: dict[str, Any] = Field(default_factory=dict)
    greeting: str = ""
    status: Literal["enabled", "disabled"]


class CreateWidgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    greeting: str = Field(default="", max_length=500)
    theme: dict[str, Any] = Field(default_factory=dict)


class UpdateWidgetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    greeting: str | None = Field(default=None, max_length=500)
    theme: dict[str, Any] | None = None
    status: Literal["enabled", "disabled"] | None = None


class AllowedOrigin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    origin: str


class CreateAllowedOriginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: str


class EmbedSnippetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snippet: str
    loader_url: str
    data_widget_id: str


class GuardrailConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    config: dict[str, Any] = Field(default_factory=dict)


class FloorViolation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error: Literal["floor_violation"] = "floor_violation"
    key_path: str
    attempted_value: Any = None
    floor_value: Any = None


class SigningKeyVersionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    created_at: datetime
