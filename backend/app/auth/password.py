"""Single source of truth for user-login password hashing.

Backed by fastapi-users' ``PasswordHelper`` (pwdlib / argon2) so that hashes
written by provisioning and the dev seed verify against the same algorithm the
login flow uses. Never logs plaintext or hashes.
"""

from __future__ import annotations

from fastapi_users.password import PasswordHelper

# Module-level singleton; reused by the UserManager, provisioning, and the seed.
password_helper = PasswordHelper()


def hash_password(password: str) -> str:
    return password_helper.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    valid, _ = password_helper.verify_and_update(plain, hashed)
    return valid
