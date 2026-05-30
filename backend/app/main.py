from fastapi import FastAPI

from app.api.routes.admin_members_and_leads import router as admin_members_and_leads_router
from app.api.routes.admin_widgets import router as admin_widgets_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.health import router as health_router
from app.api.routes.ingest import router as ingest_router
from app.api.routes.status import router as status_router
from app.api.routes.tenancy import router as tenancy_router
from app.api.routes.widget_chat import router as widget_chat_router
from app.api.routes.widget_loader import router as widget_loader_router
from app.api.routes.widget_session import router as widget_session_router
from app.core.config import settings
from app.core.logging import setup_logging
from app.core.redaction import install_redaction_filter
from app.core.request_context import RequestIdMiddleware
from app.core.tracing import setup_tracing
from app.lifespan import lifespan

setup_logging(settings.log_level)
install_redaction_filter()

app = FastAPI(title="Albert Backend", lifespan=lifespan)
app.add_middleware(RequestIdMiddleware)
setup_tracing(app)
# Approach A (feature 006): the per-tenant WidgetCorsMiddleware was removed. The
# widget API surface emits no Access-Control-Allow-Origin, so the browser
# same-origin policy blocks cross-origin reads; embedding is bounded by the
# per-tenant frame-ancestors CSP on embed.html and tenant identity by the token.

app.include_router(health_router)
app.include_router(status_router)
app.include_router(ingest_router)
app.include_router(auth_router)
app.include_router(widget_session_router)
app.include_router(widget_chat_router)
app.include_router(widget_loader_router)
app.include_router(admin_widgets_router)
app.include_router(admin_members_and_leads_router)
app.include_router(tenancy_router)
app.include_router(chat_router)
