import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_public() -> None:
    response = client.get("/health")
    assert response.status_code == 200


def test_predict_missing_token() -> None:
    response = client.post("/predict")
    assert response.status_code == 401


def test_predict_wrong_token() -> None:
    response = client.post("/predict", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_predict_correct_token(service_token: str) -> None:
    response = client.post(
        "/predict", headers={"Authorization": f"Bearer {service_token}"}
    )
    assert response.status_code == 200
    assert response.json() == {"label": "unknown", "confidence": 0.0}


def test_predict_malformed_header() -> None:
    bad = client.post("/predict", headers={"Authorization": "Token abc"})
    assert bad.status_code == 401
    empty = client.post("/predict", headers={"Authorization": "Bearer "})
    assert empty.status_code == 401


def test_predict_unset_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVICE_AUTH_TOKEN", raising=False)
    response = client.post("/predict", headers={"Authorization": "Bearer anything"})
    assert response.status_code == 401
