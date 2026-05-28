"""Classical visitor-intent classifier runtime.

Loads the Phase 4A-repair joblib artifact, verifies its SHA-256, and exposes a
small predict API for FastAPI handlers. No tenant identity is accepted here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from app.schemas import ClassifyResponse

MODEL_VERSION = "classical-intent-logreg-v0.1.0"
CONFIDENCE_THRESHOLD = 0.70
EXPECTED_ARTIFACT_SHA256 = "9f153212badb6a85529ebf1cff22894134cc4d6b0eec473322d4f79230f0ee1a"
ARTIFACT_PATH = Path(__file__).resolve().parent.parent / "artifacts" / "classical_intent_logreg.joblib"
LABELS = {"faq_rag", "lead_capture", "human_escalate", "spam", "other_agent"}


@dataclass(frozen=True)
class ModelState:
    model_version: str
    artifact_sha256: str | None
    loaded: bool
    error: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class IntentClassifier:
    def __init__(
        self,
        artifact_path: Path = ARTIFACT_PATH,
        expected_sha256: str = EXPECTED_ARTIFACT_SHA256,
    ) -> None:
        self.artifact_path = artifact_path
        self.expected_sha256 = expected_sha256
        self._model: Any | None = None
        self._state = ModelState(
            model_version=MODEL_VERSION,
            artifact_sha256=None,
            loaded=False,
            error="not_loaded",
        )
        self.load()

    @property
    def state(self) -> ModelState:
        return self._state

    def load(self) -> None:
        try:
            actual_sha256 = sha256_file(self.artifact_path)
            if actual_sha256 != self.expected_sha256:
                self._model = None
                self._state = ModelState(
                    model_version=MODEL_VERSION,
                    artifact_sha256=actual_sha256,
                    loaded=False,
                    error="artifact_sha256_mismatch",
                )
                return
            self._model = joblib.load(self.artifact_path)
            self._state = ModelState(
                model_version=MODEL_VERSION,
                artifact_sha256=actual_sha256,
                loaded=True,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            self._model = None
            self._state = ModelState(
                model_version=MODEL_VERSION,
                artifact_sha256=None,
                loaded=False,
                error=exc.__class__.__name__,
            )

    def predict(self, text: str) -> ClassifyResponse:
        if self._model is None or not self._state.loaded or self._state.artifact_sha256 is None:
            raise RuntimeError("classifier artifact is not loaded")

        predicted_label = str(self._model.predict([text])[0])
        if predicted_label not in LABELS:
            raise RuntimeError("classifier returned an unknown label")

        confidence = self._predict_confidence(text, predicted_label)
        threshold_applied = confidence < CONFIDENCE_THRESHOLD
        final_label = "other_agent" if threshold_applied else predicted_label
        return ClassifyResponse(
            label=final_label,  # type: ignore[arg-type]
            confidence=confidence,
            model_version=MODEL_VERSION,
            artifact_sha256=self._state.artifact_sha256,
            threshold_applied=threshold_applied,
            predicted_label=predicted_label,  # type: ignore[arg-type]
            predicted_confidence=confidence,
        )

    def _predict_confidence(self, text: str, predicted_label: str) -> float:
        if hasattr(self._model, "predict_proba"):
            probabilities = self._model.predict_proba([text])[0]
            classes = list(self._model.classes_)
            return float(probabilities[classes.index(predicted_label)])
        if hasattr(self._model, "decision_function"):
            scores = self._model.decision_function([text])[0]
            classes = list(self._model.classes_)
            return 1.0 if classes[int(scores.argmax())] == predicted_label else 0.0
        return 1.0


classifier = IntentClassifier()
