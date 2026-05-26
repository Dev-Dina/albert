"""Visitor-facing widget schemas. NEVER declare a tenant_id field here."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WidgetPublicView(BaseModel):
    """Public, visitor-safe projection of a widget."""

    model_config = ConfigDict(extra="forbid")

    public_widget_id: str
    theme: dict[str, Any] = Field(default_factory=dict)
    greeting: str = ""
