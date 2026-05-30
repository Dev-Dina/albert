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


def test_tool_name_attribute_is_safe() -> None:
    # The agent's tool-call span attribute must pass the policy (no forbidden
    # substring; "token" is not inside "tool_name").
    assert tracing.is_safe_span_attribute("tool_name", "rag_search")
    assert tracing.is_safe_span_attribute("tool_name", "capture_lead")
    assert tracing.is_safe_span_attribute("tool_name", "escalate")


def test_tool_span_is_a_noop_context_manager_when_disabled() -> None:
    # With tracing disabled (global no-op provider), tool_span must still be a
    # usable context manager that yields a (non-recording) span and never raises.
    with tracing.tool_span("rag_search") as span:
        assert span is not None
        assert span.is_recording() is False
