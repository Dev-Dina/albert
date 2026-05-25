from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "modelserver",
        "app": "albert",
    }


def test_predict_placeholder() -> None:
    response = client.post("/predict")
    assert response.status_code == 200
    assert response.json() == {"label": "unknown", "confidence": 0.0}
