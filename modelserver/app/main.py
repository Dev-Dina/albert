from fastapi import Depends, FastAPI, HTTPException, status

from app.auth import require_service_token
from app.classifier import classifier
from app.schemas import ClassifyRequest, ClassifyResponse

app = FastAPI(title="Albert Modelserver")


@app.get("/health")
async def health() -> dict[str, str | bool | None]:
    """Report service liveness and identity."""
    state = classifier.state
    return {
        "status": "ok",
        "service": "modelserver",
        "app": "albert",
        "model_version": state.model_version,
        "artifact_sha256": state.artifact_sha256,
        "loaded": state.loaded,
    }


@app.post("/predict", dependencies=[Depends(require_service_token)])
@app.post("/classify", dependencies=[Depends(require_service_token)])
async def predict(payload: ClassifyRequest) -> ClassifyResponse:
    """Classify visitor intent; `/predict` remains a temporary alias."""
    try:
        return classifier.predict(payload.text)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="classifier unavailable",
        ) from exc
