from fastapi import Depends, FastAPI, Request

from app.auth import require_service_token
from app.rails import evaluate_input, evaluate_output
from app.schemas import GuardrailRequest, GuardrailResponse
from app.tracing import safe_set_span_attribute, setup_tracing

app = FastAPI(title="Albert Guardrails")
setup_tracing(app)


@app.get("/health")
async def health() -> dict[str, str]:
    """Report service liveness and identity."""
    return {"status": "ok", "service": "guardrails", "app": "albert"}


@app.post("/check-input", dependencies=[Depends(require_service_token)])
@app.post("/guardrails/input", dependencies=[Depends(require_service_token)])
async def check_input(payload: GuardrailRequest, request: Request) -> GuardrailResponse:
    """Inspect inbound visitor text before it reaches model/agent code."""
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        safe_set_span_attribute("request_id", request_id)
    response = evaluate_input(payload)
    safe_set_span_attribute("guardrail_decision", response.decision)
    safe_set_span_attribute("redaction_count", response.redaction_summary.total if response.redaction_summary else 0)
    return response


@app.post("/check-output", dependencies=[Depends(require_service_token)])
@app.post("/guardrails/output", dependencies=[Depends(require_service_token)])
async def check_output(payload: GuardrailRequest, request: Request) -> GuardrailResponse:
    """Inspect model/agent output before returning or persisting it."""
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        safe_set_span_attribute("request_id", request_id)
    response = evaluate_output(payload)
    safe_set_span_attribute("guardrail_decision", response.decision)
    safe_set_span_attribute("redaction_count", response.redaction_summary.total if response.redaction_summary else 0)
    return response
