"""Optional OpenTelemetry tracing setup for guardrails."""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.redaction import redact

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


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


def is_safe_span_attribute(name: str, value: Any) -> bool:
    normalized = name.lower().replace("-", "_")
    if any(forbidden in normalized for forbidden in FORBIDDEN_ATTRIBUTE_NAMES):
        return False
    if value is None or isinstance(value, (bool, int, float)):
        return True
    return redact(str(value)).total == 0


def safe_set_span_attribute(name: str, value: Any) -> None:
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
    global _TRACING_CONFIGURED
    if not _env_bool("OTEL_ENABLED"):
        return

    service_name = os.getenv("OTEL_SERVICE_NAME", "albert-guardrails")
    environment = os.getenv("OTEL_ENVIRONMENT", "local")
    exporter = os.getenv("OTEL_TRACES_EXPORTER", "otlp")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")

    if not _TRACING_CONFIGURED:
        provider = TracerProvider(
            resource=Resource.create(
                {
                    "service.name": service_name,
                    "deployment.environment": environment,
                }
            )
        )
        if exporter == "otlp" and endpoint:
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        trace.set_tracer_provider(provider)
        _TRACING_CONFIGURED = True

    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/health",
        server_request_hook=_server_request_hook,
    )
