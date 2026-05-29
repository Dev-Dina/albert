"""Canonical platform-independent UUID column type.

Single source of truth so every model renders UUIDs identically on every
backend: native ``uuid`` on PostgreSQL (unchanged DDL) and dashed ``CHAR(36)``
elsewhere (e.g. the SQLite unit-test engine). The storage format is
byte-for-byte identical to fastapi-users' own ``GUID`` (the type backing
``User.id``), so user-FK JOINs resolve consistently on SQLite as well as on
Postgres.

We deliberately DEFINE this locally rather than importing
``fastapi_users_db_sqlalchemy.generics.GUID``. Importing that submodule eagerly
runs the ``fastapi_users_db_sqlalchemy`` package ``__init__``, which imports
``fastapi_users.db`` while the package is only partially initialized; the
re-export block in ``fastapi_users.db`` then fails and is silently swallowed,
leaving ``fastapi_users.db`` cached WITHOUT ``SQLAlchemyBaseUserTableUUID`` for
the rest of the process. Because every model imports this module (and a model
is imported before ``user.py``), that circular-import landmine crashed the whole
app at import time on Postgres CI. Defining ``GUID`` here — importing only
SQLAlchemy — removes the trigger entirely.

Use ``GUID`` for every UUID column instead of
``sqlalchemy.dialects.postgresql.UUID(as_uuid=True)``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CHAR, TypeDecorator
from sqlalchemy.dialects.postgresql import UUID

__all__ = ["GUID"]


class GUID(TypeDecorator):
    """Platform-independent UUID type.

    PostgreSQL: native ``uuid``. Elsewhere: ``CHAR(36)`` holding the dashed
    string form. Result values are always ``uuid.UUID``. Storage matches
    fastapi-users' ``GUID`` so cross-table UUID JOINs (notably to ``users.id``)
    work on every dialect.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID())
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        if not isinstance(value, uuid.UUID):
            return str(uuid.UUID(value))
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            return uuid.UUID(value)
        return value
