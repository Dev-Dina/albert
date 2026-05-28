"""POST /api/v1/widget/session — public token-exchange endpoint (US1).

Tenant identity is derived from the widget row resolved by widget_id; the
request body MUST NOT carry tenant_id (enforced by schema `extra='forbid'`).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.widget_session import WidgetSessionRequest, WidgetSessionResponse
from app.services.widget_session_service import WidgetSessionError, exchange

router = APIRouter(prefix="/api/v1/widget", tags=["widget"])


@router.post("/session", response_model=WidgetSessionResponse)
async def post_widget_session(
    payload: WidgetSessionRequest,
    origin: str | None = Header(default=None, alias="Origin"),
    db: AsyncSession = Depends(get_db),
) -> WidgetSessionResponse:
    if not origin:
        # FR-011: token exchange requires a browser-set Origin header.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Origin header required",
        )
    try:
        return await exchange(db, public_widget_id=payload.widget_id, origin=origin)
    except WidgetSessionError as exc:
        # US1: surface as 403 with an opaque body. US2 keeps the body uniform
        # across {bad origin, widget disabled, widget not found}.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="forbidden"
        ) from exc
