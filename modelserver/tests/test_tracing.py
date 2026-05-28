from fastapi import FastAPI

from app import tracing


def test_tracing_disabled_is_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    app = FastAPI()

    tracing.setup_tracing(app)

    assert tracing._TRACING_CONFIGURED is False


def test_sensitive_attribute_names_are_rejected() -> None:
    assert tracing.is_safe_span_attribute("request_id", "req-123")
    assert tracing.is_safe_span_attribute("model_version", "v1")
    assert not tracing.is_safe_span_attribute("Authorization", "Bearer secret")
    assert not tracing.is_safe_span_attribute("SERVICE_AUTH_TOKEN", "secret")
    assert not tracing.is_safe_span_attribute("raw_prompt", "secret")
    assert not tracing.is_safe_span_attribute("safe_note", "contact admin@example.test")
    assert tracing.is_safe_span_attribute("text_length", 42)
