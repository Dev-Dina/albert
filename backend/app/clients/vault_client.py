import httpx

from app.core.config import settings

_TIMEOUT = 2.0


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
