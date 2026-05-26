from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.status import router as status_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.lifespan import lifespan

setup_logging(settings.log_level)

app = FastAPI(title="Albert Backend", lifespan=lifespan)
app.include_router(health_router)
app.include_router(status_router)
