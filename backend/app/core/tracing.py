"""Optional OpenTelemetry tracing setup for the backend."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import settings

logger = logging.getLogger(__name__)

FORBIDDEN_ATTRIBUTE_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "service_auth_token",
    "gemini_api_key",
    "api_key",
    "password",
    "secret",
    "token",
    "raw_user_message",
    "raw_prompt",
    "system_prompt",
}

_TRACING_CONFIGURED = False
_HTTPX_INSTRUMENTED = False


def _enabled(value: bool | str) -> bool:
    if isinstance(value, bool):
        return value
    return value.lower() in {"1", "true", "yes", "on"}


def is_safe_span_attribute(name: str, value: Any) -> bool:
    """Return whether a custom span attribute is safe for Albert traces."""
    del value
    normalized = name.lower().replace("-", "_")
    return not any(forbidden in normalized for forbidden in FORBIDDEN_ATTRIBUTE_NAMES)


def safe_set_span_attribute(name: str, value: Any) -> None:
    """Set a span attribute only when its name is on the safe side of the policy."""
    if not is_safe_span_attribute(name, value):
        return
    trace.get_current_span().set_attribute(name, value)


def _server_request_hook(span: Any, scope: dict[str, Any]) -> None:
    if not span or not span.is_recording():
        return
    for key, value in scope.get("headers", []):
        if key.lower() == b"x-request-id":
            span.set_attribute("request_id", value.decode("ascii", errors="ignore"))
            return


def setup_tracing(app: FastAPI) -> None:
    """Configure OpenTelemetry when enabled; otherwise remain a no-op."""
    global _HTTPX_INSTRUMENTED, _TRACING_CONFIGURED
    if not _enabled(settings.otel_enabled):
        return

    if not _TRACING_CONFIGURED:
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "deployment.environment": settings.otel_environment,
            }
        )
        provider = TracerProvider(resource=resource)
        if settings.otel_traces_exporter == "otlp" and settings.otel_exporter_otlp_endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(
                    OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
                )
            )
        trace.set_tracer_provider(provider)
        _TRACING_CONFIGURED = True

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/health",
        server_request_hook=_server_request_hook,
    )
    if not _HTTPX_INSTRUMENTED:
        HTTPXClientInstrumentor().instrument()
        _HTTPX_INSTRUMENTED = True
    logger.info("OpenTelemetry tracing enabled for %s", settings.otel_service_name)
