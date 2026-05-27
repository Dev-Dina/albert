from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "modelserver"
    assert body["app"] == "albert"
    assert body["model_version"] == "classical-intent-logreg-v0.1.0"
    assert body["artifact_sha256"] == "9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a"
    assert body["loaded"] is True


def test_predict_classifies(service_token: str) -> None:
    response = client.post(
        "/predict",
        headers={"Authorization": f"Bearer {service_token}"},
        json={"text": "how can I check payment methods"},
    )
    assert response.status_code == 200
    assert response.json()["label"] == "faq_rag"
