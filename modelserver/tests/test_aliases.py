from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(service_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {service_token}"}


def test_classify_missing_token() -> None:
    assert client.post("/classify").status_code == 401


def test_classify_wrong_token() -> None:
    response = client.post("/classify", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_classify_correct_token_matches_predict(service_token: str) -> None:
    payload = {"text": "I need to file a complaint about payment issue"}
    classify = client.post("/classify", headers=_auth(service_token), json=payload)
    predict = client.post("/predict", headers=_auth(service_token), json=payload)
    assert classify.status_code == 200
    assert predict.status_code == 200
    assert classify.json() == predict.json()


def test_predict_still_works(service_token: str) -> None:
    response = client.post(
        "/predict",
        headers=_auth(service_token),
        json={"text": "how can I check payment methods"},
    )
    assert response.status_code == 200
    assert response.json()["label"] == "faq_rag"


def test_health_public() -> None:
    assert client.get("/health").status_code == 200
