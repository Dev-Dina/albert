"""Service for the tenant-admin Leads + Members surface (FR-050 exception 1).

All functions are tenant-scoped by the ``tenant_id`` the route layer resolves
from the caller's verified ``tenant_admin`` membership. No function here accepts
a tenant id sourced from a request body, query, or path.

Member invitation mirrors the existing add-admin flow in
``tenancy/provisioning.py`` (create the user with ``hash_password`` then insert
a membership row) rather than a magic-link invite, because no email service is
in scope. ``member.invite`` / ``member.remove`` audit entries are written for
every write.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import hash_password
from app.db.models.lead import Lead
from app.db.models.membership import TenantMembership
from app.db.models.user import User
from app.repositories import leads_repo, members_repo
from app.tenancy.audit import record_audit

logger = logging.getLogger(__name__)


class EmailAlreadyRegisteredError(Exception):
    """The invited email already belongs to a platform user (409)."""


class MemberNotFoundError(Exception):
    """No ``role='member'`` row for ``(tenant_id, user_id)`` (404)."""


class CannotRemoveSelfError(Exception):
    """A tenant_admin may not remove their own membership here (409)."""


# ---------------------------------------------------------------------------
# Leads (read-only)
# ---------------------------------------------------------------------------

async def list_leads(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    since: datetime | None = None,
    until: datetime | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Lead]:
    return await leads_repo.list_for_tenant(
        session,
        tenant_id=tenant_id,
        since=since,
        until=until,
        status=status,
        limit=limit,
        offset=offset,
    )


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------

async def list_members(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    limit: int = 100,
    offset: int = 0,
) -> list[tuple[TenantMembership, str]]:
    return await members_repo.list_members_for_tenant(
        session, tenant_id=tenant_id, limit=limit, offset=offset
    )


async def invite_member(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
    password: str,
) -> tuple[User, TenantMembership]:
    """Create a user (if absent) + a ``role='member'`` membership atomically.

    Returns ``(user, membership)``. Raises ``EmailAlreadyRegisteredError`` if a
    user with this email already exists (mirrors add-admin's duplicate guard).
    Writes a ``member.invite`` audit entry. Does not commit — the caller owns
    the transaction.
    """
    existing = await members_repo.get_user_by_email(session, email)
    if existing is not None:
        raise EmailAlreadyRegisteredError(
            f"A user with email {email!r} already exists."
        )

    user = User(
        id=uuid.uuid4(),
        email=email,
        hashed_password=hash_password(password),
        is_active=True,
    )
    session.add(user)
    await session.flush()

    membership = await members_repo.add_member(
        session, tenant_id=tenant_id, user_id=user.id
    )

    await record_audit(
        db=session,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="member.invite",
        meta={"target_email": email},
    )

    logger.info(
        "member.invited tenant_id=%s new_member=%s by actor=%s",
        tenant_id,
        user.id,
        actor_user_id,
    )
    return user, membership


async def remove_member(
    session: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
) -> uuid.UUID:
    """Remove a member's membership row (the ``User`` row is preserved).

    Guards (ordered): the caller may not remove themselves
    (``CannotRemoveSelfError``); the target must be a member of this tenant
    (``MemberNotFoundError``). Writes a ``member.remove`` audit entry. Does not
    commit — the caller owns the transaction.
    """
    if user_id == actor_user_id:
        raise CannotRemoveSelfError(
            "A tenant admin cannot remove their own membership."
        )

    membership = await members_repo.get_member(
        session, tenant_id=tenant_id, user_id=user_id
    )
    if membership is None:
        raise MemberNotFoundError(
            f"User {user_id!r} is not a member of tenant {tenant_id!r}."
        )

    await members_repo.remove_member(session, membership)

    await record_audit(
        db=session,
        actor_user_id=actor_user_id,
        target_tenant_id=tenant_id,
        action="member.remove",
        meta={"target_user_id": str(user_id)},
    )

    logger.info(
        "member.removed tenant_id=%s removed_user=%s by actor=%s",
        tenant_id,
        user_id,
        actor_user_id,
    )
    return user_id
