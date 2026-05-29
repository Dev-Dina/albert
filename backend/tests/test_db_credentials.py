"""Unit tests for Vault-backed runtime DB credential resolution (Phase 6.2A.3).

Proves:
  - Vault values override the env fallback when a secret path is configured.
  - The env fallback is used when Vault is disabled (no path) or unreachable.
  - MIGRATION_DATABASE_URL is never used as the runtime DATABASE_URL.

No real Vault is required: the sync KV read is monkeypatched.
"""

from __future__ import annotations

import pytest

from app.core import db_credentials
from app.core.config import Settings

_FALLBACK = "postgresql+asyncpg://albert_app:dev@localhost:5433/albert"


def test_no_path_returns_env_fallback() -> None:
    assert (
        db_credentials.resolve_database_url(
            vault_addr="http://vault:8200",
            vault_token="t",
            vault_mount="secret",
            vault_db_secret_path=None,
            fallback_url=_FALLBACK,
        )
        == _FALLBACK
    )


def test_vault_unreachable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db_credentials, "_read_vault_kv2", lambda *a, **k: None)
    assert (
        db_credentials.resolve_database_url(
            vault_addr="http://vault:8200",
            vault_token="t",
            vault_mount="secret",
            vault_db_secret_path="database/albert_app",
            fallback_url=_FALLBACK,
        )
        == _FALLBACK
    )


def test_vault_explicit_url_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    vault_url = "postgresql+asyncpg://albert_app:vault-secret@db:5432/albert"
    monkeypatch.setattr(db_credentials, "_read_vault_kv2", lambda *a, **k: {"url": vault_url})
    assert (
        db_credentials.resolve_database_url(
            vault_addr="http://vault:8200",
            vault_token="t",
            vault_mount="secret",
            vault_db_secret_path="database/albert_app",
            fallback_url=_FALLBACK,
        )
        == vault_url
    )


def test_vault_username_password_spliced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        db_credentials,
        "_read_vault_kv2",
        lambda *a, **k: {"username": "albert_app", "password": "vault-secret"},
    )
    resolved = db_credentials.resolve_database_url(
        vault_addr="http://vault:8200",
        vault_token="t",
        vault_mount="secret",
        vault_db_secret_path="database/albert_app",
        fallback_url=_FALLBACK,
    )
    # Creds come from Vault; host/db preserved from the fallback template.
    assert resolved == "postgresql+asyncpg://albert_app:vault-secret@localhost:5433/albert"
    assert "dev@" not in resolved  # the dev fallback password is gone


def test_settings_uses_vault_when_path_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        db_credentials,
        "_read_vault_kv2",
        lambda *a, **k: {"username": "albert_app", "password": "from-vault"},
    )
    monkeypatch.setenv("DATABASE_URL", _FALLBACK)
    monkeypatch.setenv("VAULT_DB_SECRET_PATH", "database/albert_app")
    s = Settings()
    assert s.database_url == "postgresql+asyncpg://albert_app:from-vault@localhost:5433/albert"


def test_settings_env_fallback_without_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VAULT_DB_SECRET_PATH", raising=False)
    monkeypatch.setenv("DATABASE_URL", _FALLBACK)
    s = Settings()
    assert s.database_url == _FALLBACK


def test_migration_url_not_used_as_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = "postgresql+asyncpg://albert_app:dev@localhost:5433/albert"
    admin = "postgresql+asyncpg://postgres:postgres@localhost:5433/albert"
    monkeypatch.delenv("VAULT_DB_SECRET_PATH", raising=False)
    monkeypatch.setenv("DATABASE_URL", runtime)
    monkeypatch.setenv("MIGRATION_DATABASE_URL", admin)
    s = Settings()
    # Runtime config never picks up the admin/migration URL.
    assert s.database_url == runtime
    assert s.database_url != admin
