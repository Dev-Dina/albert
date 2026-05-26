import logging

import pytest

import app.core.redaction as redaction_mod
from app.core.redaction import (
    RedactionFilter,
    install_redaction_filter,
    redact,
)


def test_redacts_email() -> None:
    result = redact("reach me at alice@example.com please")
    assert "alice@example.com" not in result.text
    assert result.counts.get("email") == 1


def test_redacts_phone() -> None:
    result = redact("call +1 (415) 555-2671 today")
    assert "555-2671" not in result.text
    assert result.counts.get("phone", 0) >= 1


def test_redacts_token_like() -> None:
    secret = "abcdef0123456789abcdef0123456789abcd"  # 36 chars
    result = redact(f"the value is {secret} ok")
    assert secret not in result.text
    assert result.counts.get("token_like", 0) >= 1


def test_redacts_api_key_assignment() -> None:
    result = redact("api_key=sk-livesecretvalue123456")
    assert "sk-livesecretvalue123456" not in result.text
    assert result.counts.get("secret_assignment", 0) >= 1


def test_redacts_password_token_secret_assignments() -> None:
    for raw in ("password=hunter2value", "token=abc.def.ghijk", "secret=topsecretvalue"):
        result = redact(raw)
        value = raw.split("=", 1)[1]
        assert value not in result.text
        assert "[REDACTED:secret_assignment]" in result.text


def test_redacts_bearer_token() -> None:
    result = redact("Authorization: Bearer abc123def456ghi789")
    assert "abc123def456ghi789" not in result.text
    assert result.counts.get("bearer_token", 0) >= 1


def test_fake_api_key_not_leaked_raw() -> None:
    fake = "sk-FAKE1234567890abcdefGHIJKL"
    result = redact(f"here is the key {fake} use it")
    assert fake not in result.text
    assert "[REDACTED:" in result.text


def test_counts_present_but_raw_absent() -> None:
    result = redact("email a@b.com and password=supersecretvalue")
    assert result.total >= 2
    assert "a@b.com" not in result.text
    assert "supersecretvalue" not in result.text
    # Counts carry types, never raw values.
    assert "supersecretvalue" not in str(result.counts)
    assert "a@b.com" not in str(result.counts)


class _Boom:
    """Stand-in pattern whose subn always raises, to exercise fail-closed."""

    def subn(self, *args: object, **kwargs: object) -> tuple[str, int]:
        raise RuntimeError("detector failure")


def test_fail_closed_does_not_return_raw(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(redaction_mod, "_PATTERNS", (("x", _Boom()),))
    result = redact("password=supersecretvalue email a@b.com")
    assert "supersecretvalue" not in result.text
    assert "a@b.com" not in result.text
    assert result.text == "[REDACTED]"


def test_filter_redacts_record_and_clears_args() -> None:
    f = RedactionFilter()
    record = logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="token=%s",
        args=("supersecretvalue123456",),
        exc_info=None,
    )
    assert f.filter(record) is True
    rendered = record.getMessage()
    assert "supersecretvalue123456" not in rendered
    assert "[REDACTED:" in rendered


def test_install_redaction_filter_redacts_via_caplog(
    caplog: pytest.LogCaptureFixture,
) -> None:
    install_redaction_filter()
    logger = logging.getLogger("albert.test.redaction.caplog")
    with caplog.at_level(logging.INFO):
        logger.info("password=supersecretvalue123 contact a@b.com")
    assert "supersecretvalue123" not in caplog.text
    assert "a@b.com" not in caplog.text
    assert "[REDACTED:" in caplog.text
