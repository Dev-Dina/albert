"""Resolve the service-to-service auth token, preferring Vault when configured.

Phase 6.4. Backend → modelserver/guardrails calls carry a bearer credential
(``SERVICE_AUTH_TOKEN``). In real deployments that credential should come from
Vault; local dev falls back to the plain ``SERVICE_AUTH_TOKEN`` from .env.

Precedence (mirrors ``db_credentials.resolve_database_url``):
  1. ``VAULT_SERVICE_AUTH_SECRET_PATH`` unset → use the env token (dev fallback).
  2. Set but Vault unreachable / the secret missing → fall back to the env token
     (so local dev never breaks when Vault is down).
  3. Secret found → use its ``token`` / ``service_auth_token`` / ``value`` field.

Synchronous so it can run during ``Settings`` construction (the async
``vault_client.read_secret`` cannot). The token is never logged. Reuses the KV v2
read helper from ``db_credentials`` so there is a single Vault-read code path.

The sidecars (modelserver, guardrails) do NOT call Vault directly — they stay
lean and read ``SERVICE_AUTH_TOKEN`` from env, which the platform injects from
this same Vault secret. See docs/SECRETS.md.
"""

from __future__ import annotations

from app.core.db_credentials import _read_vault_kv2

# Keys the service-auth secret may expose, in priority order.
_TOKEN_KEYS = ("token", "service_auth_token", "value")


def resolve_service_auth_token(
    *,
    vault_addr: str,
    vault_token: str,
    vault_mount: str,
    vault_service_auth_secret_path: str | None,
    fallback_token: str | None,
) -> str | None:
    """Return the service auth token: Vault-backed when configured, else fallback."""
    if not vault_service_auth_secret_path:
        return fallback_token

    data = _read_vault_kv2(vault_addr, vault_token, vault_mount, vault_service_auth_secret_path)
    if not data:
        # Vault disabled / unreachable / secret missing → preserve dev fallback.
        return fallback_token

    for key in _TOKEN_KEYS:
        value = data.get(key)
        if value:
            return str(value)
    return fallback_token
