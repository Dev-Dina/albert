from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.status import router as status_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redaction import install_redaction_filter
from app.core.request_context import RequestIdMiddleware

setup_logging(settings.log_level)
install_redaction_filter()

app = FastAPI(title="Albert Backend")
app.add_middleware(RequestIdMiddleware)
app.include_router(health_router)
app.include_router(status_router)
app.include_router(auth_router)
