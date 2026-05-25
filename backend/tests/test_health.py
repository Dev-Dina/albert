from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "backend"
    assert body["app"] == "albert"
    assert "environment" in body


def test_status_dependencies_returns_200(monkeypatch) -> None:
    # Tests must not require a running Vault: stub the client.
    async def fake_check_vault_health() -> dict:
        return {"reachable": False}

    monkeypatch.setattr(
        "app.api.routes.status.check_vault_health", fake_check_vault_health
    )
    response = client.get("/status/dependencies")
    assert response.status_code == 200
    assert response.json() == {"vault": {"reachable": False}}
