from fastapi import APIRouter

from app.core.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    """Report service liveness and identity."""
    return {
        "status": "ok",
        "service": settings.service_name,
        "app": settings.app_name,
    }
