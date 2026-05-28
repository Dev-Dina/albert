from pathlib import Path

from fastapi.testclient import TestClient

from app.classifier import EXPECTED_ARTIFACT_SHA256, IntentClassifier
from app.main import app

client = TestClient(app)

LABELS = {"faq_rag", "lead_capture", "human_escalate", "spam", "other_agent"}


def _auth(service_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {service_token}"}


def test_classify_returns_required_label(service_token: str) -> None:
    response = client.post(
        "/classify",
        headers=_auth(service_token),
        json={"text": "how can I check payment methods"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["label"] in LABELS
    assert body["label"] == "faq_rag"
    assert body["confidence"] >= 0.70
    assert body["threshold_applied"] is False
    assert body["artifact_sha256"] == EXPECTED_ARTIFACT_SHA256
    assert body["model_version"] == "classical-intent-logreg-v0.1.0"


def test_predict_alias_matches_classify(service_token: str) -> None:
    payload = {"text": "I need to file a complaint about payment issue"}
    classify = client.post("/classify", headers=_auth(service_token), json=payload)
    predict = client.post("/predict", headers=_auth(service_token), json=payload)
    assert classify.status_code == 200
    assert predict.status_code == 200
    assert predict.json() == classify.json()


def test_low_confidence_falls_back_to_other_agent(service_token: str) -> None:
    response = client.post(
        "/classify",
        headers=_auth(service_token),
        json={"text": "zzzz qqqq xxyy unrelated impossible gibberish"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["label"] == "other_agent"
    assert body["threshold_applied"] is True
    assert body["predicted_label"] in LABELS
    assert body["predicted_confidence"] < 0.70


def test_request_with_tenant_id_is_rejected(service_token: str) -> None:
    response = client.post(
        "/classify",
        headers=_auth(service_token),
        json={"text": "how can I check payment methods", "tenant_id": "not-trusted"},
    )
    assert response.status_code == 422


def test_artifact_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    artifact = tmp_path / "bad.joblib"
    artifact.write_bytes(b"not the expected model")
    classifier = IntentClassifier(artifact_path=artifact, expected_sha256=EXPECTED_ARTIFACT_SHA256)
    assert classifier.state.loaded is False
    assert classifier.state.error == "artifact_sha256_mismatch"


def test_modelserver_runtime_dependencies_exclude_heavy_frameworks() -> None:
    root = Path(__file__).resolve().parents[1]
    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8").casefold()
    lock = (root / "uv.lock").read_text(encoding="utf-8").casefold()
    assert "torch" not in pyproject
    assert "transformers" not in pyproject
    assert 'name = "torch"' not in lock
    assert 'name = "transformers"' not in lock
