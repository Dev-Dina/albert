from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Report service liveness and identity. Fast and dependency-free."""
    return {
        "status": "ok",
        "service": "backend",
        "app": settings.app_name,
        "environment": settings.app_env,
    }
