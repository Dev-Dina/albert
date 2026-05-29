"""Canonical platform-independent UUID column type.

Single source of truth so every model renders UUIDs identically on every
backend: native ``uuid`` on PostgreSQL (unchanged DDL) and dashed ``CHAR(36)``
elsewhere. Reuses fastapi-users' ``GUID`` — the type backing ``User.id`` — so
user-FK JOINs resolve consistently on the SQLite unit-test engine as well as on
Postgres (where both were already native ``uuid``).

Use ``GUID`` for every UUID column instead of
``sqlalchemy.dialects.postgresql.UUID(as_uuid=True)``.
"""

from fastapi_users_db_sqlalchemy.generics import GUID

__all__ = ["GUID"]
