from app.clients.vault_client import read_secret


async def get_secret_value(name: str, fallback: str | None = None) -> str | None:
    """Fetch a secret from Vault path ``app/{name}``; return fallback if missing.

    No real secrets are required for local dev, and secret values are never logged.
    """
    secret = await read_secret(f"app/{name}")
    if secret is None:
        return fallback
    if name in secret:
        return secret[name]
    if "value" in secret:
        return secret["value"]
    return fallback
