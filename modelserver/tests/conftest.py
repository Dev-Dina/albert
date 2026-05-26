import pytest

_TOKEN = "test-service-token"


@pytest.fixture(autouse=True)
def _set_service_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure a known SERVICE_AUTH_TOKEN for every test (auto-restored)."""
    monkeypatch.setenv("SERVICE_AUTH_TOKEN", _TOKEN)


@pytest.fixture
def service_token() -> str:
    """The service token set by the autouse fixture above."""
    return _TOKEN
