"""fastapi-users wiring: user DB adapter, UserManager, JWT auth backend.

This is the ONLY user-login authentication system. It issues + verifies JWTs
that carry only ``sub`` (user id); role and tenant are resolved per request
from the database (see ``app/auth/roles.py`` / ``app/deps.py``), never from the
token. The separate per-tenant widget-session token system (``app/core/security.py``)
is unrelated and untouched.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin
from fastapi_users.authentication import (
    AuthenticationBackend,
    BearerTransport,
    JWTStrategy,
)
from fastapi_users.db import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.password import password_helper
from app.core.config import settings
from app.db.models.user import User
from app.db.session import get_db


async def get_user_db(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncGenerator[SQLAlchemyUserDatabase, None]:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    """Credential verification + token issuance via fastapi-users.

    Token secrets reuse the platform JWT secret; the reset/verify flows are not
    exposed (provisioning-only account creation), so these exist for completeness.
    """

    reset_password_token_secret = settings.jwt_secret.get_secret_value()
    verification_token_secret = settings.jwt_secret.get_secret_value()

    def __init__(self, user_db: SQLAlchemyUserDatabase) -> None:
        super().__init__(user_db, password_helper)


async def get_user_manager(
    user_db: Annotated[SQLAlchemyUserDatabase, Depends(get_user_db)],
) -> AsyncGenerator[UserManager, None]:
    yield UserManager(user_db)


bearer_transport = BearerTransport(tokenUrl="auth/login")


def get_jwt_strategy() -> JWTStrategy:
    return JWTStrategy(
        secret=settings.jwt_secret.get_secret_value(),
        lifetime_seconds=settings.access_token_expire_minutes * 60,
        algorithm=settings.jwt_algorithm,
    )


auth_backend = AuthenticationBackend(
    name="jwt",
    transport=bearer_transport,
    get_strategy=get_jwt_strategy,
)

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

# Resolves + verifies the bearer token and loads the active user from the DB.
current_active_user = fastapi_users.current_user(active=True)
