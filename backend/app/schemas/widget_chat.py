"""Widget chat request/response. FR-009: no tenant_id field accepted."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WidgetChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class WidgetChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    message: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
