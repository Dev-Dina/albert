"""Tenant status enforcement on the widget surfaces (feature 009, FR-012/FR-013).

Drives the REAL ``widget_session_service.exchange`` (handshake) and
``deps.get_widget_session`` (chat auth) with stubs, proving a non-active tenant is
refused while an active tenant proceeds — so the tenant status is the deciding gate.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.api import deps
from app.api.deps import get_widget_session
from app.clients import vault_client
from app.core.security import mint_widget_session_token
from app.repositories import widget_repo
from app.services.widget_session_service import WidgetSessionError, exchange

_TENANT = uuid.uuid4()
_WIDGET = uuid.uuid4()
_PUBLIC = "Acm" + "X" * 19  # 22 base62 chars
_ORIGIN = "https://x.example.com"
_KEY = b"dev-tenant-signing-key-bytes-32!"


class _StatusSession:
    """Fake session: reports ``tenants.status`` reads as the configured status, and
    returns None for any other read (set_config from tenant_context, etc.)."""

    def __init__(self, status: str | None) -> None:
        self._status = status

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement).lower()
        value = self._status if ("tenants.status" in sql or "from tenants" in sql) else None

        class _R:
            def scalar_one_or_none(self_inner):
                return value

        return _R()


class _ActiveKey:
    version = 1


# ---------------------------------------------------------------------------
# Handshake — widget_session_service.exchange
# ---------------------------------------------------------------------------

async def test_exchange_refused_for_non_active_tenant(monkeypatch) -> None:
    async def _fake_lookup(session, public_widget_id):
        return widget_repo.PublicWidgetLookup(
            widget_id=_WIDGET, tenant_id=_TENANT, status="enabled"
        )

    monkeypatch.setattr(widget_repo, "get_by_public_id", _fake_lookup)

    # Suspended tenant → the status gate raises before any key/vault work.
    with pytest.raises(WidgetSessionError):
        await exchange(_StatusSession("suspended"), public_widget_id=_PUBLIC, origin=_ORIGIN)

    # Erased behaves the same.
    with pytest.raises(WidgetSessionError):
        await exchange(_StatusSession("erased"), public_widget_id=_PUBLIC, origin=_ORIGIN)


# ---------------------------------------------------------------------------
# Chat auth — deps.get_widget_session
# ---------------------------------------------------------------------------

def _valid_token() -> str:
    return mint_widget_session_token(
        tenant_id=_TENANT,
        widget_id=_WIDGET,
        public_widget_id=_PUBLIC,
        origin=_ORIGIN,
        key_version=1,
        key_material=_KEY,
    )


class _FakeRequest:
    def __init__(self, token: str) -> None:
        self.headers = {"Authorization": f"Bearer {token}"}


def _wire_chat(monkeypatch) -> None:
    async def _fake_active_key(db, tenant_id):
        return _ActiveKey()

    async def _fake_read_key(tenant_id):
        return _KEY

    monkeypatch.setattr(deps, "_fetch_active_key_version", _fake_active_key)
    monkeypatch.setattr(vault_client, "read_tenant_widget_signing_key", _fake_read_key)


async def test_chat_refused_for_non_active_tenant(monkeypatch) -> None:
    """A still-valid widget token is refused (401) once its tenant is non-active."""
    _wire_chat(monkeypatch)
    gen = get_widget_session(_FakeRequest(_valid_token()), _StatusSession("suspended"))
    with pytest.raises(HTTPException) as exc:
        await gen.__anext__()
    assert exc.value.status_code == 401


async def test_chat_allowed_for_active_tenant(monkeypatch) -> None:
    """Control: the same valid token + wiring yields claims when the tenant is active,
    proving the status read is the deciding gate (not some other failure)."""
    _wire_chat(monkeypatch)
    gen = get_widget_session(_FakeRequest(_valid_token()), _StatusSession("active"))
    claims = await gen.__anext__()
    assert claims.tenant_id == _TENANT
    await gen.aclose()
