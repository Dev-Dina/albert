from fastapi import FastAPI

from app.core import tracing


def test_tracing_disabled_is_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(tracing.settings, "otel_enabled", False)
    app = FastAPI()

    tracing.setup_tracing(app)

    assert tracing._TRACING_CONFIGURED is False


def test_sensitive_attribute_names_are_rejected() -> None:
    assert tracing.is_safe_span_attribute("request_id", "req-123")
    assert tracing.is_safe_span_attribute("classifier_label", "faq_rag")
    assert not tracing.is_safe_span_attribute("Authorization", "Bearer secret")
    assert not tracing.is_safe_span_attribute("service_auth_token", "secret")
    assert not tracing.is_safe_span_attribute("raw_user_message", "alice@example.com")
    assert not tracing.is_safe_span_attribute("cookie", "session=secret")
    assert not tracing.is_safe_span_attribute("safe_note", "api_key=sk-fake000000000000")
    assert tracing.is_safe_span_attribute("text_length", 42)
