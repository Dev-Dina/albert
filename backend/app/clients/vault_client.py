import base64
import time
import uuid

import httpx

from app.core.config import settings

_TIMEOUT = 2.0
_WIDGET_KEY_CACHE_TTL_SECONDS = 60.0

# Per-tenant in-process cache of (key_material, fetched_at). Caps churn against
# Vault on hot paths. Cleared on rotation by the admin write helper.
_widget_key_cache: dict[uuid.UUID, tuple[bytes, float]] = {}


async def check_vault_health() -> dict:
    """Return Vault reachability. Never raises — safe for local dev / status checks."""
    url = f"{settings.vault_addr}/v1/sys/health"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return {"reachable": False}
    return {"reachable": response.status_code < 500, "status_code": response.status_code}


async def read_secret(path: str) -> dict | None:
    """Read a KV v2 secret from Vault. Returns None if missing or unreachable.

    Does not raise for missing secrets in local setup, and never logs the token.
    """
    url = f"{settings.vault_addr}/v1/{settings.vault_mount}/data/{path}"
    headers = {"X-Vault-Token": settings.vault_token.get_secret_value()}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError:
        return None
    if response.status_code == 200:
        return response.json().get("data", {}).get("data")
    return None


async def _write_secret(path: str, data: dict) -> int | None:
    """Write a KV v2 secret. Returns the new version, or None on transport failure."""
    url = f"{settings.vault_addr}/v1/{settings.vault_mount}/data/{path}"
    headers = {"X-Vault-Token": settings.vault_token.get_secret_value()}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, headers=headers, json={"data": data})
    except httpx.HTTPError:
        return None
    if response.status_code in (200, 204):
        return int(response.json().get("data", {}).get("version", 1))
    return None


def _widget_key_path(tenant_id: uuid.UUID) -> str:
    return f"tenant/{tenant_id}/widget_signing_key"


async def read_tenant_widget_signing_key(tenant_id: uuid.UUID) -> bytes | None:
    """Return the active widget signing key material for the tenant, or None.

    Uses a 60s in-process cache. Key material is never logged.
    """
    now = time.monotonic()
    cached = _widget_key_cache.get(tenant_id)
    if cached is not None and now - cached[1] < _WIDGET_KEY_CACHE_TTL_SECONDS:
        return cached[0]
    data = await read_secret(_widget_key_path(tenant_id))
    if data is None:
        return None
    encoded = data.get("key")
    if not isinstance(encoded, str):
        return None
    try:
        material = base64.b64decode(encoded)
    except (ValueError, TypeError):
        return None
    _widget_key_cache[tenant_id] = (material, now)
    return material


async def write_tenant_widget_signing_key(tenant_id: uuid.UUID, material: bytes) -> int | None:
    """Write new key material; returns the new Vault KV v2 version (or None on failure).

    Invalidates the in-process cache so the next read fetches the new material.
    """
    encoded = base64.b64encode(material).decode("ascii")
    version = await _write_secret(_widget_key_path(tenant_id), {"key": encoded})
    _widget_key_cache.pop(tenant_id, None)
    return version


def invalidate_tenant_widget_signing_key_cache(tenant_id: uuid.UUID) -> None:
    """Test/admin hook to drop the in-process cache for a tenant."""
    _widget_key_cache.pop(tenant_id, None)
