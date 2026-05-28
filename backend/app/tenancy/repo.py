"""Base repository with mandatory tenant scoping (defense-in-depth).

Every query against a tenant-owned table MUST go through a subclass of
``TenantRepository``.  The base class injects ``.where(Model.tenant_id == tid)``
on every read, and sets ``tenant_id`` on every write, regardless of whether RLS
is active on the current connection.

Why both RLS and repo-layer filtering?
  RLS catches a query a developer forgets to scope.
  The repo layer is the habit that prevents forgetting in the first place.
  Belt and suspenders: if one layer is misconfigured, the other still holds.
"""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

from app.db.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class TenantRepository(Generic[ModelT]):
    """Base async repository scoped to a single tenant.

    Subclasses declare ``model: type[ModelT]`` and call ``super().__init__``
    with the current tenant_id and db session::

        class ConversationRepo(TenantRepository[Conversation]):
            model = Conversation

        repo = ConversationRepo(tenant_id=tid, db=db)
        convs = await repo.list()

    All read helpers apply an explicit ``.where(model.tenant_id == self.tenant_id)``
    predicate in addition to the RLS policy set on the connection.
    All write helpers force ``tenant_id`` on the created/updated row.
    """

    model: type[ModelT]

    def __init__(self, tenant_id: uuid.UUID, db: AsyncSession) -> None:
        self.tenant_id = tenant_id
        self.db = db

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _base_query(self):
        """Return a SELECT scoped to this tenant."""
        return select(self.model).where(self.model.tenant_id == self.tenant_id)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    async def get(self, row_id: uuid.UUID) -> ModelT | None:
        """Fetch a single row by primary key, scoped to this tenant."""
        result = await self.db.execute(
            self._base_query().where(self.model.id == row_id)  # type: ignore[attr-defined]
        )
        return result.scalar_one_or_none()

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[ModelT]:
        """Return a page of rows scoped to this tenant."""
        result = await self.db.execute(
            self._base_query().limit(limit).offset(offset)
        )
        return list(result.scalars().all())

    async def count(self) -> int:
        """Count rows scoped to this tenant."""
        from sqlalchemy import func, select as sa_select

        result = await self.db.execute(
            sa_select(func.count()).select_from(self.model).where(
                self.model.tenant_id == self.tenant_id  # type: ignore[attr-defined]
            )
        )
        return result.scalar_one()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    async def create(self, **kwargs: Any) -> ModelT:
        """Insert a new row, always stamping tenant_id from the repo context.

        Any tenant_id supplied in kwargs is silently overwritten — the repo
        context is the only valid source.
        """
        kwargs["tenant_id"] = self.tenant_id
        row = self.model(**kwargs)
        self.db.add(row)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def update(self, row: ModelT, **kwargs: Any) -> ModelT:
        """Update fields on an existing row.

        Raises ValueError if the row belongs to a different tenant — this is a
        programming error, not a user error.
        """
        if getattr(row, "tenant_id", None) != self.tenant_id:  # type: ignore[attr-defined]
            raise ValueError(
                f"Cross-tenant update attempt: row.tenant_id={getattr(row, 'tenant_id', None)!r} "
                f"!= repo.tenant_id={self.tenant_id!r}"
            )
        kwargs.pop("tenant_id", None)  # tenant_id is immutable after creation
        for key, value in kwargs.items():
            setattr(row, key, value)
        await self.db.flush()
        await self.db.refresh(row)
        return row

    async def delete(self, row: ModelT) -> None:
        """Delete a row, asserting it belongs to this tenant."""
        if getattr(row, "tenant_id", None) != self.tenant_id:  # type: ignore[attr-defined]
            raise ValueError(
                f"Cross-tenant delete attempt: row.tenant_id={getattr(row, 'tenant_id', None)!r} "
                f"!= repo.tenant_id={self.tenant_id!r}"
            )
        await self.db.delete(row)
        await self.db.flush()
