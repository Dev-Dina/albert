import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

# (alias, original) pairs that must behave identically.
ALIASES = [
    ("/guardrails/input", "/check-input"),
    ("/guardrails/output", "/check-output"),
]


def _auth(service_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {service_token}"}


@pytest.mark.parametrize("alias", [a for a, _ in ALIASES])
def test_alias_missing_token(alias: str) -> None:
    assert client.post(alias).status_code == 401


@pytest.mark.parametrize("alias", [a for a, _ in ALIASES])
def test_alias_wrong_token(alias: str) -> None:
    response = client.post(alias, headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


@pytest.mark.parametrize("alias,original", ALIASES)
def test_alias_matches_original(alias: str, original: str, service_token: str) -> None:
    alias_resp = client.post(alias, headers=_auth(service_token))
    orig_resp = client.post(original, headers=_auth(service_token))
    assert alias_resp.status_code == 200
    assert orig_resp.status_code == 200
    assert alias_resp.json() == orig_resp.json()


@pytest.mark.parametrize("original", [o for _, o in ALIASES])
def test_original_still_works(original: str, service_token: str) -> None:
    response = client.post(original, headers=_auth(service_token))
    assert response.status_code == 200
    assert response.json() == {"allowed": True, "reason": "phase_1_placeholder"}


def test_health_public() -> None:
    assert client.get("/health").status_code == 200
