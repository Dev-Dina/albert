"""Schemas for the tenant-admin CMS content endpoints (feature 007, US1).

Every shape here is tenant-admin-scoped; the tenant id is derived from the
caller's verified JWT membership (``AdminIdentityDep``) and is NEVER accepted as
a field on any of these models. Body length is capped at 100,000 chars and must
be non-empty after stripping (FR-014).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

_MAX_BODY = 100_000
_MAX_TITLE = 200
_MAX_SLUG = 200


class CmsPageCreate(BaseModel):
    """Body of ``POST /api/v1/admin/cms/pages``.

    ``slug`` is optional — derived from ``title`` when omitted. ``is_published``
    defaults to ``True`` per spec v1 (no draft authoring UI ships in v1).
    """

    title: str = Field(min_length=1, max_length=_MAX_TITLE)
    body: str = Field(min_length=1, max_length=_MAX_BODY)
    slug: str | None = Field(default=None, max_length=_MAX_SLUG)
    is_published: bool = True

    @field_validator("title", "body")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be empty")
        return v


class CmsPageUpdate(BaseModel):
    """Body of ``PUT /api/v1/admin/cms/pages/{page_id}``.

    All fields optional; at least one must be provided.
    """

    title: str | None = Field(default=None, min_length=1, max_length=_MAX_TITLE)
    body: str | None = Field(default=None, min_length=1, max_length=_MAX_BODY)
    slug: str | None = Field(default=None, max_length=_MAX_SLUG)
    is_published: bool | None = None

    @field_validator("title", "body")
    @classmethod
    def _not_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("must not be empty")
        return v

    def has_any(self) -> bool:
        return any(
            v is not None
            for v in (self.title, self.body, self.slug, self.is_published)
        )


class CmsPageResponse(BaseModel):
    """One row of the CMS pages API."""

    id: UUID
    title: str
    slug: str
    body: str
    is_published: bool
    created_at: datetime
    updated_at: datetime
