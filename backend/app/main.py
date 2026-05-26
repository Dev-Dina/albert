from fastapi import FastAPI

from app.api.routes.auth import router as auth_router
from app.api.routes.health import router as health_router
from app.api.routes.status import router as status_router
from app.api.routes.widget_chat import router as widget_chat_router
from app.api.routes.widget_loader import router as widget_loader_router
from app.api.routes.widget_session import router as widget_session_router
from app.core.config import settings
from app.core.logging import setup_logging

setup_logging(settings.log_level)

app = FastAPI(title="Albert Backend")
app.include_router(health_router)
app.include_router(status_router)
app.include_router(auth_router)
app.include_router(widget_session_router)
app.include_router(widget_chat_router)
app.include_router(widget_loader_router)
