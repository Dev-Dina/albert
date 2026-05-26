"""Widget session token-exchange schemas.

FR-009: visitor-facing request bodies MUST NOT carry tenant_id. ``extra="forbid"``
rejects any client-supplied tenant_id at parse time.
"""

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.widget import WidgetPublicView


class WidgetSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    widget_id: str = Field(pattern=r"^[A-Za-z0-9]{22}$")


class WidgetSessionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_token: str
    expires_in: int
    ttl_seconds: int
    widget: WidgetPublicView | None = None
