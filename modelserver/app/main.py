from fastapi import Depends, FastAPI, HTTPException, Request, status

from app.auth import require_service_token
from app.classifier import classifier
from app.schemas import ClassifyRequest, ClassifyResponse
from app.tracing import safe_set_span_attribute, setup_tracing

app = FastAPI(title="Albert Modelserver")
setup_tracing(app)


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
async def predict(payload: ClassifyRequest, request: Request) -> ClassifyResponse:
    """Classify visitor intent; `/predict` remains a temporary alias."""
    try:
        response = classifier.predict(payload.text)
        request_id = request.headers.get("X-Request-ID")
        if request_id:
            safe_set_span_attribute("request_id", request_id)
        safe_set_span_attribute("model_version", response.model_version)
        safe_set_span_attribute("classifier_label", response.label)
        safe_set_span_attribute("text_length", len(payload.text))
        return response
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="classifier unavailable",
        ) from exc
