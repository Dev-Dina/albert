from fastapi import FastAPI

from app import tracing


def test_tracing_disabled_is_noop(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("OTEL_ENABLED", raising=False)
    app = FastAPI()

    tracing.setup_tracing(app)

    assert tracing._TRACING_CONFIGURED is False


def test_sensitive_attribute_names_are_rejected() -> None:
    assert tracing.is_safe_span_attribute("request_id", "req-123")
    assert tracing.is_safe_span_attribute("guardrail_decision", "allow")
    assert not tracing.is_safe_span_attribute("Authorization", "Bearer secret")
    assert not tracing.is_safe_span_attribute("GEMINI_API_KEY", "secret")
    assert not tracing.is_safe_span_attribute("system_prompt", "secret")
    assert not tracing.is_safe_span_attribute("safe_note", "Authorization: Bearer fake")
    assert tracing.is_safe_span_attribute("text_length", 42)
