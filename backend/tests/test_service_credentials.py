"""Service-auth token Vault resolution + fail-closed config (Phase 6.4)."""

from __future__ import annotations

import logging

import pytest

from app.core import service_credentials
from app.core.config import Settings


def test_no_path_uses_env_fallback() -> None:
    token = service_credentials.resolve_service_auth_token(
        vault_addr="http://vault:8200",
        vault_token="root",
        vault_mount="secret",
        vault_service_auth_secret_path=None,
        fallback_token="env-token",
    )
    assert token == "env-token"


def test_vault_token_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_credentials, "_read_vault_kv2", lambda *a, **k: {"token": "vault-token"}
    )
    token = service_credentials.resolve_service_auth_token(
        vault_addr="http://vault:8200",
        vault_token="root",
        vault_mount="secret",
        vault_service_auth_secret_path="service/albert",
        fallback_token="env-token",
    )
    assert token == "vault-token"


def test_vault_unreachable_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service_credentials, "_read_vault_kv2", lambda *a, **k: None)
    token = service_credentials.resolve_service_auth_token(
        vault_addr="http://vault:8200",
        vault_token="root",
        vault_mount="secret",
        vault_service_auth_secret_path="service/albert",
        fallback_token="env-token",
    )
    assert token == "env-token"


@pytest.mark.parametrize("key", ["token", "service_auth_token", "value"])
def test_supported_secret_keys(monkeypatch: pytest.MonkeyPatch, key: str) -> None:
    monkeypatch.setattr(
        service_credentials, "_read_vault_kv2", lambda *a, **k: {key: "vault-token"}
    )
    token = service_credentials.resolve_service_auth_token(
        vault_addr="x",
        vault_token="root",
        vault_mount="secret",
        vault_service_auth_secret_path="p",
        fallback_token="env-token",
    )
    assert token == "vault-token"


def test_resolved_token_not_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(
        service_credentials, "_read_vault_kv2", lambda *a, **k: {"token": "super-secret-tok"}
    )
    with caplog.at_level(logging.DEBUG):
        service_credentials.resolve_service_auth_token(
            vault_addr="x",
            vault_token="root",
            vault_mount="secret",
            vault_service_auth_secret_path="p",
            fallback_token="env",
        )
    assert "super-secret-tok" not in caplog.text


def test_settings_resolves_service_token_from_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        service_credentials, "_read_vault_kv2", lambda *a, **k: {"token": "vault-token"}
    )
    settings = Settings(vault_service_auth_secret_path="service/albert")
    assert settings.service_auth_token.get_secret_value() == "vault-token"


def test_settings_env_fallback_when_no_path() -> None:
    settings = Settings(service_auth_token="env-token")
    assert settings.service_auth_token.get_secret_value() == "env-token"


def test_settings_fail_closed_non_dev_when_empty() -> None:
    with pytest.raises(ValueError, match="SERVICE_AUTH_TOKEN"):
        Settings(app_env="production", service_auth_token="")


def test_settings_dev_env_allows_empty_token() -> None:
    # Local/dev must not hard-fail when the token is blank (no real secret needed).
    settings = Settings(app_env="local", service_auth_token="")
    assert settings.service_auth_token.get_secret_value() == ""
