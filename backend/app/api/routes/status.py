from fastapi import APIRouter

from app.clients.vault_client import check_vault_health

router = APIRouter()


@router.get("/status/dependencies")
async def dependencies() -> dict[str, dict[str, bool]]:
    """Report reachability of backend dependencies. Never returns 500 on an outage."""
    vault = await check_vault_health()
    return {"vault": {"reachable": bool(vault.get("reachable", False))}}
