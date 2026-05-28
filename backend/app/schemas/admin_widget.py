"""Tenant-admin widget schemas.

All requests derive their tenant from the caller's membership; admin bodies
MUST NOT carry tenant_id either.
"""

from datetime import datetime
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _validate_origin(raw: str) -> str:
    """Validate + normalise an exact origin (scheme + host + port).

    Rejects: paths, queries, fragments, trailing slashes, wildcards,
    non-http(s) schemes, and plain http for non-localhost hosts.

    Normalises: lowercases scheme + host, strips the default port. Mirrors
    the constraints in data-model.md §E3.
    """
    if not isinstance(raw, str) or not raw:
        raise ValueError("origin must be a non-empty string")
    if "*" in raw:
        raise ValueError("origin must not contain wildcards")
    # `urlsplit` is happy with weird inputs; we tighten with explicit checks.
    if "://" not in raw:
        raise ValueError("origin must include a scheme (http/https)")

    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ValueError("origin scheme must be http or https")
    if parts.path:
        # Includes a single trailing slash — Origin headers never carry one.
        raise ValueError("origin must not contain a path or trailing slash")
    if parts.query:
        raise ValueError("origin must not contain a query string")
    if parts.fragment:
        raise ValueError("origin must not contain a fragment")
    if not parts.hostname:
        raise ValueError("origin must include a host")

    host = parts.hostname.lower()
    scheme = parts.scheme.lower()
    if scheme == "http" and host not in _LOCALHOST_HOSTS:
        raise ValueError("plain http is only allowed for localhost")

    port = parts.port
    if port is not None and port == _DEFAULT_PORTS.get(scheme):
        port = None

    if port is None:
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


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

    @field_validator("origin")
    @classmethod
    def _normalise_origin(cls, value: str) -> str:
        return _validate_origin(value)


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
