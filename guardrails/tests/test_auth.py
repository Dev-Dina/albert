import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PROTECTED = ["/check-input", "/check-output"]


def test_health_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200


@pytest.mark.parametrize("path", PROTECTED)
def test_missing_token(path: str) -> None:
    response = client.post(path)
    assert response.status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_wrong_token(path: str) -> None:
    response = client.post(path, headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_correct_token(path: str, service_token: str) -> None:
    response = client.post(path, headers={"Authorization": f"Bearer {service_token}"}, json={"text": "hello"})
    assert response.status_code == 200
    assert response.json()["allowed"] is True


@pytest.mark.parametrize("path", PROTECTED)
def test_malformed_header(path: str) -> None:
    response = client.post(path, headers={"Authorization": "Token abc"})
    assert response.status_code == 401


@pytest.mark.parametrize("path", PROTECTED)
def test_unset_token_fails_closed(path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_AUTH_TOKEN", raising=False)
    response = client.post(path, headers={"Authorization": "Bearer anything"})
    assert response.status_code == 401
