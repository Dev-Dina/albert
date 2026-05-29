"""Resolve the runtime database URL, preferring Vault when configured.

Phase 6.2A.3. The runtime backend connects as the dedicated non-superuser role
(`albert_app`). Its password is a secret and should come from Vault in any real
deployment; local dev falls back to the plain ``DATABASE_URL`` from .env.

Precedence:
  1. If ``VAULT_DB_SECRET_PATH`` is unset → use the env ``DATABASE_URL`` (dev fallback).
  2. If set but Vault is unreachable / the secret is missing → fall back to env
     ``DATABASE_URL`` (so local dev never breaks when Vault is down).
  3. If the Vault secret provides a full ``url``/``database_url`` → use it.
  4. Else if it provides ``username`` + ``password`` → splice them into the env
     ``DATABASE_URL`` (host/port/dbname from the secret override when present).

This is a synchronous resolver so it can run during ``Settings`` construction
(the async ``vault_client.read_secret`` cannot). Secret values are never logged.
It is intentionally self-contained (imports no app config) to avoid an import
cycle with ``app.core.config``.
"""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy.engine import make_url

_TIMEOUT = 2.0


def _read_vault_kv2(addr: str, token: str, mount: str, path: str) -> dict[str, Any] | None:
    """Read a KV v2 secret synchronously. Returns the inner data dict or None.

    Never raises for an unreachable Vault or a missing secret (dev-friendly),
    and never logs the token or the secret contents.
    """
    url = f"{addr}/v1/{mount}/data/{path}"
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            response = client.get(url, headers={"X-Vault-Token": token})
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return response.json().get("data", {}).get("data")
    return None


def resolve_database_url(
    *,
    vault_addr: str,
    vault_token: str,
    vault_mount: str,
    vault_db_secret_path: str | None,
    fallback_url: str | None,
) -> str | None:
    """Return the runtime DB URL: Vault-backed when configured, else the fallback."""
    if not vault_db_secret_path:
        return fallback_url

    data = _read_vault_kv2(vault_addr, vault_token, vault_mount, vault_db_secret_path)
    if not data:
        # Vault disabled / unreachable / secret missing → preserve dev fallback.
        return fallback_url

    explicit = data.get("url") or data.get("database_url")
    if explicit:
        return str(explicit)

    username = data.get("username")
    password = data.get("password")
    if not (username and password) or not fallback_url:
        return fallback_url

    url = make_url(fallback_url).set(username=str(username), password=str(password))
    if data.get("host"):
        url = url.set(host=str(data["host"]))
    if data.get("port"):
        url = url.set(port=int(data["port"]))
    if data.get("dbname"):
        url = url.set(database=str(data["dbname"]))
    return url.render_as_string(hide_password=False)
