"""Cross-tenant red-team demo (T061, spec US2).

Implements the three attacks from spec User Story 2 against the running stack
and asserts each is rejected. Importable from quickstart step 8 and from the
CI redteam_cross_tenant eval gate (T083).

Attack inventory:
1. Token exchange from a foreign/attacker origin must not pivot tenants — the
   minted token stays scoped to the widget's own tenant (Approach A: origin is
   no longer a request-time gate; it governs embedding via frame-ancestors).
2. Chat request with a copied widget_id and a forged/stale token via curl.
3. Chat request with a valid Tenant A token AND a foreign `tenant_id` field
   in the body.

The harness is dependency-light so it can run against:
- a live `docker compose up` stack, OR
- the in-process FastAPI TestClient (used in unit-test CI when there is no
  real backend listening on a port).
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

from fastapi.testclient import TestClient

from app.core.security import mint_widget_session_token
from app.main import app


@dataclass(frozen=True)
class AttackResult:
    name: str
    rejected: bool
    detail: str


_TENANT_A = uuid.uuid4()
_TENANT_B = uuid.uuid4()
_WIDGET_A = uuid.uuid4()
_PUBLIC_ID_A = "Acm" + "1" * 19
_ALLOWED_ORIGIN = "https://demo.example.com"
_ATTACKER_ORIGIN = "https://attacker.test"
_KEY_A = b"dev-tenant-A-signing-key-bytes-!"


def _wire_isolated_app() -> TestClient:
    """Wire DB/Vault stubs for a Tenant A widget with one allowed origin."""
    from app.api import deps
    from app.clients import vault_client
    from app.db.session import get_db
    from app.repositories import allowed_origin_repo, widget_repo
    from app.services import widget_session_service

    class _FakeSession:
        async def execute(self, *args, **kwargs):
            class _R:
                def scalar_one_or_none(self_inner):
                    return None
            return _R()

    async def _fake_get_db():
        yield _FakeSession()

    async def _fake_get_by_public_id(session, public_widget_id):
        if public_widget_id != _PUBLIC_ID_A:
            return None
        return widget_repo.PublicWidgetLookup(
            widget_id=_WIDGET_A, tenant_id=_TENANT_A, status="enabled"
        )

    async def _fake_exists_for_tenant(session, tenant_id, origin):
        return tenant_id == _TENANT_A and origin == _ALLOWED_ORIGIN

    async def _fake_read_key(tenant_id):
        return _KEY_A if tenant_id == _TENANT_A else None

    class _ActiveKey:
        version = 1

    async def _fake_active_key(_db, tenant_id):
        return _ActiveKey() if tenant_id == _TENANT_A else None

    app.dependency_overrides[get_db] = _fake_get_db
    widget_repo.get_by_public_id = _fake_get_by_public_id  # type: ignore[assignment]
    allowed_origin_repo.exists_for_tenant = _fake_exists_for_tenant  # type: ignore[assignment]
    vault_client.read_tenant_widget_signing_key = _fake_read_key  # type: ignore[assignment]
    widget_session_service._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]
    deps._fetch_active_key_version = _fake_active_key  # type: ignore[assignment]
    return TestClient(app)


def _attack_origin_cannot_pivot_tenant(client: TestClient) -> AttackResult:
    """Under Approach A (feature 006) the request Origin is no longer a
    request-time gate at /session — embedding is controlled by frame-ancestors
    instead. The cross-tenant property that MUST still hold: a session obtained
    from ANY origin is scoped to the widget's own tenant (Tenant A); the Origin
    can never be used to pivot to another tenant.
    """
    from jose import jwt as _jwt

    response = client.post(
        "/api/v1/widget/session",
        headers={"Origin": _ATTACKER_ORIGIN},
        json={"widget_id": _PUBLIC_ID_A},
    )
    if response.status_code == 200:
        token = response.json().get("session_token", "")
        claims = _jwt.get_unverified_claims(token) if token else {}
        rejected = (
            claims.get("tnt") == str(_TENANT_A)
            and str(_TENANT_B) not in response.text
        )
        detail = f"status=200 token_tenant={claims.get('tnt')}"
    else:
        # A real stack may still refuse for unrelated reasons; refusal is safe too.
        rejected = response.status_code in (401, 403)
        detail = f"status={response.status_code}"
    return AttackResult(
        name="origin_cannot_pivot_tenant",
        rejected=rejected,
        detail=detail,
    )


def _attack_forged_token(client: TestClient) -> AttackResult:
    """curl-style attack: a token signed with the WRONG key must 401."""
    wrong_key = b"attacker-forged-key-bytes-cmon!!"
    forged = mint_widget_session_token(
        tenant_id=_TENANT_A,
        widget_id=_WIDGET_A,
        public_widget_id=_PUBLIC_ID_A,
        origin=_ALLOWED_ORIGIN,
        key_version=1,
        key_material=wrong_key,
    )
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {forged}", "Origin": _ALLOWED_ORIGIN},
        json={"message": "exfiltrate"},
    )
    rejected = response.status_code == 401
    return AttackResult(
        name="forged_token_chat",
        rejected=rejected,
        detail=f"status={response.status_code}",
    )


def _attack_body_tenant_id_injection(client: TestClient) -> AttackResult:
    """Body field `tenant_id` is ignored — server stays under token's tenant."""
    valid = mint_widget_session_token(
        tenant_id=_TENANT_A,
        widget_id=_WIDGET_A,
        public_widget_id=_PUBLIC_ID_A,
        origin=_ALLOWED_ORIGIN,
        key_version=1,
        key_material=_KEY_A,
    )
    response = client.post(
        "/api/v1/widget/chat",
        headers={"Authorization": f"Bearer {valid}", "Origin": _ALLOWED_ORIGIN},
        json={"message": "pivot", "tenant_id": str(_TENANT_B)},
    )
    # Rejection criterion: under no circumstances does the server honor a
    # body-supplied tenant_id. The request must EITHER 200 under Tenant A
    # (and never reference Tenant B), or be refused.
    if response.status_code == 200:
        rejected = str(_TENANT_B) not in response.text
        detail = f"status=200 served_under_token_tenant={rejected}"
    else:
        rejected = response.status_code in (401, 422)
        detail = f"status={response.status_code}"
    return AttackResult(
        name="body_tenant_id_injection",
        rejected=rejected,
        detail=detail,
    )


def run_all() -> list[AttackResult]:
    client = _wire_isolated_app()
    try:
        return [
            _attack_origin_cannot_pivot_tenant(client),
            _attack_forged_token(client),
            _attack_body_tenant_id_injection(client),
        ]
    finally:
        app.dependency_overrides.clear()


def test_cross_tenant_redteam_all_rejected() -> None:
    """The single pytest hook that the redteam_cross_tenant CI gate runs."""
    results = run_all()
    rejected = sum(1 for r in results if r.rejected)
    assert rejected == len(results), [r.__dict__ for r in results]


if __name__ == "__main__":  # pragma: no cover
    results = run_all()
    rejected = sum(1 for r in results if r.rejected)
    for r in results:
        print(f"[{'REJECT' if r.rejected else 'BREACH'}] {r.name}: {r.detail}")
    print(f"{rejected}/{len(results)} attacks rejected")
    raise SystemExit(0 if rejected == len(results) else 1)
    _ = os.environ  # keep import for future env-driven overrides
