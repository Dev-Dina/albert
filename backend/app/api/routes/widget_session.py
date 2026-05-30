"""POST /api/v1/widget/session — public token-exchange endpoint.

Tenant identity is derived from the widget row resolved by widget_id; the
request body MUST NOT carry tenant_id (enforced by schema `extra='forbid'`).

US2-hardened: two independent rate-limit gates are checked on EVERY call —
per-source-IP and per-tenant. Either gate alone can refuse with 429 +
Retry-After (FR-015a). The per-tenant gate fires AFTER the widget has been
resolved (so we have a tenant id) and AFTER the per-IP gate has passed (so a
flood from one IP cannot drain the tenant budget for that tenant's legitimate
visitors — see test_widget_rate_limit.test_per_ip_exhaustion_does_not_consume_per_tenant_budget).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.rate_limit import (
    RateLimitDecision,
    capacity_from_per_minute,
    check_and_consume,
    per_minute_to_refill,
)
from app.db.session import get_db
from app.repositories import widget_repo
from app.schemas.widget_session import WidgetSessionRequest, WidgetSessionResponse
from app.services.widget_session_service import WidgetSessionError, exchange

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])


def _rate_limit_response(decision: RateLimitDecision) -> HTTPException:
    """Translate a rate-limit refusal into an opaque 429.

    The body MUST NOT name the tripped dimension (FR-015c). Retry-After is
    derived from the decision so clients back off cleanly.
    """
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail="rate_limited",
        headers={"Retry-After": str(decision.retry_after_seconds)},
    )


def _client_ip(request: Request) -> str:
    """Best-effort source IP. Prefers the trusted ``X-Forwarded-For`` left-most
    entry when present; falls back to the socket peer. In Starlette/TestClient
    the socket peer is ``testclient`` so tests get a stable key.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    client = request.client
    return client.host if client else "unknown"


@router.post("/session", response_model=WidgetSessionResponse)
async def post_widget_session(
    request: Request,
    payload: WidgetSessionRequest,
    origin: str | None = Header(default=None, alias="Origin"),
    db: AsyncSession = Depends(get_db),
) -> WidgetSessionResponse:
    if not origin:
        # FR-009: token exchange requires a browser-set Origin header (fail
        # closed). Approach A: the Origin is NOT compared against the customer
        # allowlist here — that allowlist governs embedding only.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin header required",
        )

    # Gate 1: per-IP. Charged BEFORE any DB work so a flood from one IP cannot
    # exhaust the per-tenant budget for legitimate visitors on other IPs.
    ip_decision = await check_and_consume(
        "ip",
        f"ip:{_client_ip(request)}",
        capacity=capacity_from_per_minute(settings.widget_rate_limit_per_ip_per_min),
        refill_per_sec=per_minute_to_refill(settings.widget_rate_limit_per_ip_per_min),
    )
    if not ip_decision.allowed:
        raise _rate_limit_response(ip_decision)

    try:
        response = await exchange(
            db, public_widget_id=payload.widget_id, origin=origin
        )
    except WidgetSessionError as exc:
        # Uniform 403 across {malformed origin, bad origin, widget disabled,
        # widget not found, missing key} — prevents allowlist enumeration.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
        ) from exc

    # Gate 2: per-tenant. We only know the tenant after a successful exchange,
    # so this gate is checked AFTER resolve, and after the per-IP Gate 1 (so a
    # single-IP flood cannot drain the tenant budget for that tenant's legitimate
    # visitors). NOTE under Approach A: any origin with a valid public widget_id
    # now reaches this gate (the customer allowlist no longer gates exchange), so
    # this per-tenant limit is also what bounds a /session flood aimed at one
    # tenant from non-allowlisted origins.
    lookup = await widget_repo.get_by_public_id(db, payload.widget_id)
    if lookup is not None:
        tenant_decision = await check_and_consume(
            "tenant",
            f"tenant:{lookup.tenant_id}",
            capacity=capacity_from_per_minute(
                settings.widget_rate_limit_per_tenant_per_min
            ),
            refill_per_sec=per_minute_to_refill(
                settings.widget_rate_limit_per_tenant_per_min
            ),
        )
        if not tenant_decision.allowed:
            raise _rate_limit_response(tenant_decision)

    return response
