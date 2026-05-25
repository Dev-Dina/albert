from fastapi import APIRouter

from app.clients.vault_client import check_vault_health
from app.db.session import check_database_health

router = APIRouter()


@router.get("/status/dependencies")
async def dependencies() -> dict[str, dict[str, bool]]:
    """Report reachability of backend dependencies. Never returns 500 on an outage."""
    vault = await check_vault_health()
    database = await check_database_health()
    return {
        "vault": {"reachable": bool(vault.get("reachable", False))},
        "database": {"reachable": bool(database.get("reachable", False))},
    }
