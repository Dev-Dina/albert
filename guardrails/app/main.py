from fastapi import Depends, FastAPI, Request

from app.auth import require_service_token
from app.tracing import safe_set_span_attribute, setup_tracing

app = FastAPI(title="Albert Guardrails")
setup_tracing(app)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report service liveness and identity."""
    return {"status": "ok", "service": "guardrails", "app": "albert"}


@app.post("/check-input", dependencies=[Depends(require_service_token)])
@app.post("/guardrails/input", dependencies=[Depends(require_service_token)])
async def check_input(request: Request) -> dict[str, object]:
    """Placeholder input guardrail. Request body is ignored this phase."""
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        safe_set_span_attribute("request_id", request_id)
    safe_set_span_attribute("guardrail_decision", "allow")
    return {"allowed": True, "reason": "phase_1_placeholder"}


@app.post("/check-output", dependencies=[Depends(require_service_token)])
@app.post("/guardrails/output", dependencies=[Depends(require_service_token)])
async def check_output(request: Request) -> dict[str, object]:
    """Placeholder output guardrail. Request body is ignored this phase."""
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        safe_set_span_attribute("request_id", request_id)
    safe_set_span_attribute("guardrail_decision", "allow")
    return {"allowed": True, "reason": "phase_1_placeholder"}
