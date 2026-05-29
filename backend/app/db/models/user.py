from datetime import datetime

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    """Platform user account.

    Inherits id/email/hashed_password/is_active/is_superuser/is_verified from
    fastapi-users. ``is_superuser`` exists only for fastapi-users compatibility;
    Concierge authorization NEVER branches on it — it uses ``platform_role``
    (platform level) and ``tenant_memberships.role`` (tenant level) exclusively.
    """

    __tablename__ = "users"

    # Platform-level role; only legal non-NULL value is "tenant_manager".
    # Distinct from tenant_memberships.role (which is always tenant-scoped).
    platform_role: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
