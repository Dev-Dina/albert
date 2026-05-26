from fastapi import Depends, FastAPI

from app.auth import require_service_token

app = FastAPI(title="Albert Guardrails")


@app.get("/health")
async def health() -> dict[str, str]:
    """Report service liveness and identity."""
    return {"status": "ok", "service": "guardrails", "app": "albert"}


@app.post("/check-input", dependencies=[Depends(require_service_token)])
async def check_input() -> dict[str, object]:
    """Placeholder input guardrail. Request body is ignored this phase."""
    return {"allowed": True, "reason": "phase_1_placeholder"}


@app.post("/check-output", dependencies=[Depends(require_service_token)])
async def check_output() -> dict[str, object]:
    """Placeholder output guardrail. Request body is ignored this phase."""
    return {"allowed": True, "reason": "phase_1_placeholder"}
