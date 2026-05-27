from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "guardrails",
        "app": "albert",
    }


def test_check_input_placeholder(service_token: str) -> None:
    response = client.post(
        "/check-input", headers={"Authorization": f"Bearer {service_token}"}
    )
    assert response.status_code == 200
    assert response.json() == {"allowed": True, "reason": "phase_1_placeholder"}


def test_check_output_placeholder(service_token: str) -> None:
    response = client.post(
        "/check-output", headers={"Authorization": f"Bearer {service_token}"}
    )
    assert response.status_code == 200
    assert response.json() == {"allowed": True, "reason": "phase_1_placeholder"}
