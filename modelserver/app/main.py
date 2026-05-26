from fastapi import FastAPI

app = FastAPI(title="Albert Modelserver")


@app.get("/health")
async def health() -> dict[str, str]:
    """Report service liveness and identity."""
    return {"status": "ok", "service": "modelserver", "app": "albert"}


@app.post("/predict")
async def predict() -> dict[str, object]:
    """Placeholder prediction. Request body is ignored this phase."""
    return {"label": "unknown", "confidence": 0.0}
