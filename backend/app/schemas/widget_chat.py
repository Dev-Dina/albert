"""Widget chat request/response.

FR-009: the request body MUST NOT influence tenant identity. We accept the
``tenant_id`` field at parse time (``extra="ignore"``) so a hostile client
that injects it gets a clean response under the TOKEN's tenant — and a log
line names the event for operator visibility. Tightening to
``extra="forbid"`` would 422 such requests, which is *stricter* but does not
match the spec's "body field is ignored" wording (T048).
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WidgetChatRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=4000)
    conversation_id: UUID | None = None


class WidgetChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: UUID
    message: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
