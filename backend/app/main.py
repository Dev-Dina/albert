from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.status import router as status_router
from app.api.routes.tenancy import router as tenancy_router
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging(settings.log_level)

app = FastAPI(title="Albert Backend")
app.include_router(health_router)
app.include_router(status_router)
app.include_router(auth_router)
app.include_router(tenancy_router)
