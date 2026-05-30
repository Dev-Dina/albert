"""Thin typed wrapper over the Albert backend HTTP API.

Centralises Authorization-header injection so pages never touch ``httpx``
directly. Every method maps onto a single backend endpoint and returns a
shape that mirrors ``backend/app/schemas/admin_widget.py``.

Errors:
  * :class:`BackendUnauthorizedError` — 401 from the backend; caller should
    clear the local session.
  * :class:`FloorViolationError` — 422 from ``PUT /guardrail-config`` with
    the structured floor-violation body (FR-019).
  * :class:`BackendError` — base class; any other non-2xx.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx


_DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class BackendError(Exception):
    """Base error for any non-2xx response from the backend."""

    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


class BackendUnauthorizedError(BackendError):
    """401 — token missing / invalid / expired. Caller clears local session."""


class FloorViolationError(BackendError):
    """422 from PUT /guardrail-config; carries the structured violation body."""

    def __init__(
        self,
        key_path: str,
        attempted_value: Any,
        floor_value: Any,
    ) -> None:
        super().__init__(
            422,
            (
                f"Guardrail config weakens the platform floor at "
                f"{key_path!r}: attempted={attempted_value!r}, "
                f"floor={floor_value!r}"
            ),
        )
        self.key_path = key_path
        self.attempted_value = attempted_value
        self.floor_value = floor_value


@dataclass(frozen=True)
class Identity:
    """Verified identity from ``GET /auth/me`` (FR-050 exception 2).

    ``role`` is whatever the backend returns (``tenant_manager`` /
    ``tenant_admin`` / ``member`` / ``None``); the admin app maps anything
    that is not a manager/admin to the ``other`` surface in ``lib/auth.py``.
    ``tenant_id`` / ``tenant_name`` are populated only for tenant-scoped
    callers. The JWT is NEVER decoded locally — identity comes from this call.
    """

    user_id: str
    email: str
    role: str
    is_active: bool
    tenant_id: str | None
    tenant_name: str | None


@dataclass(frozen=True)
class AdminWidget:
    id: str
    public_widget_id: str
    name: str
    theme: dict[str, Any]
    greeting: str
    status: str


@dataclass(frozen=True)
class AllowedOrigin:
    id: str
    origin: str


@dataclass(frozen=True)
class EmbedSnippet:
    snippet: str
    loader_url: str
    data_widget_id: str


@dataclass(frozen=True)
class SigningKeyMeta:
    version: int
    created_at: str


# --- Platform (tenant_manager) view models ---------------------------------


@dataclass(frozen=True)
class TenantSummary:
    tenant_id: str
    name: str
    slug: str
    status: str
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class CreatedTenant:
    tenant_id: str
    name: str
    slug: str
    status: str
    first_admin_user_id: str


@dataclass(frozen=True)
class TenantCost:
    tenant_id: str
    total_events: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: str


@dataclass(frozen=True)
class CostPoint:
    date: str
    cost_usd: str
    total_tokens: int


@dataclass(frozen=True)
class AuditEntry:
    entry_id: str
    actor_user_id: str | None
    actor_email: str | None
    action: str
    target_tenant_id: str | None
    target_tenant_slug: str | None
    created_at: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class CreatedManager:
    manager_user_id: str
    email: str


# --- Tenant-admin view models ----------------------------------------------


@dataclass(frozen=True)
class LeadRow:
    lead_id: str
    name: str
    contact: str
    intent: str
    status: str
    created_at: str
    conversation_id: str | None


@dataclass(frozen=True)
class MemberRow:
    user_id: str
    email: str
    created_at: str


@dataclass(frozen=True)
class CmsPageRow:
    id: str
    title: str
    slug: str
    body: str
    is_published: bool
    created_at: str
    updated_at: str


class BackendClient:
    """Thin httpx wrapper. Stateful only in the optional ``token`` field."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        token: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get(
            "ALBERT_BACKEND_URL", "http://backend:8000"
        )).rstrip("/")
        self.token = token
        self._transport = transport

    # -- low-level ---------------------------------------------------------

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=_DEFAULT_TIMEOUT,
            transport=self._transport,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        if response.status_code == 401:
            raise BackendUnauthorizedError(401, "unauthorized")
        # Surface backend ``detail`` if present, else the raw body trimmed.
        detail = response.text[:300]
        try:
            data = response.json()
            if isinstance(data, dict):
                detail = str(
                    data.get("detail") or data.get("error") or data
                )[:300]
        except ValueError:
            pass
        raise BackendError(response.status_code, detail)

    # -- auth --------------------------------------------------------------

    def login(self, *, email: str, password: str) -> str:
        with self._client() as c:
            r = c.post(
                "/auth/login",
                json={"email": email, "password": password},
            )
        self._raise_for_status(r)
        body = r.json()
        token = body.get("access_token") or body.get("token")
        if not token:
            raise BackendError(r.status_code, "login response missing token")
        self.token = token
        return token

    def auth_me(self) -> Identity:
        """Resolve the signed-in user's verified identity.

        Maps onto the extended ``GET /auth/me`` (FR-050 exception 2). Does NOT
        decode the JWT locally — role + tenant come straight from the backend.
        401 raises :class:`BackendUnauthorizedError` so the caller clears the
        local session; 5xx / network errors propagate as :class:`BackendError`
        for a retryable error state.
        """
        with self._client() as c:
            r = c.get("/auth/me", headers=self._headers())
        self._raise_for_status(r)
        body = r.json()
        raw_tenant_id = body.get("tenant_id")
        raw_tenant_name = body.get("tenant_name")
        return Identity(
            user_id=str(body.get("id", "")),
            email=str(body.get("email", "")),
            role=str(body.get("role") or "other"),
            is_active=bool(body.get("is_active", False)),
            tenant_id=str(raw_tenant_id) if raw_tenant_id else None,
            tenant_name=str(raw_tenant_name) if raw_tenant_name else None,
        )

    # -- widgets -----------------------------------------------------------

    def list_widgets(self) -> list[AdminWidget]:
        with self._client() as c:
            r = c.get("/api/v1/admin/widgets", headers=self._headers())
        self._raise_for_status(r)
        return [_widget_from_json(item) for item in r.json()]

    def create_widget(
        self,
        *,
        name: str,
        greeting: str = "",
        theme: dict[str, Any] | None = None,
    ) -> AdminWidget:
        with self._client() as c:
            r = c.post(
                "/api/v1/admin/widgets",
                headers=self._headers(),
                json={"name": name, "greeting": greeting, "theme": theme or {}},
            )
        self._raise_for_status(r)
        return _widget_from_json(r.json())

    def update_widget(
        self,
        widget_id: str,
        *,
        name: str | None = None,
        greeting: str | None = None,
        theme: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> AdminWidget:
        body = {
            k: v
            for k, v in {
                "name": name,
                "greeting": greeting,
                "theme": theme,
                "status": status,
            }.items()
            if v is not None
        }
        with self._client() as c:
            r = c.patch(
                f"/api/v1/admin/widgets/{widget_id}",
                headers=self._headers(),
                json=body,
            )
        self._raise_for_status(r)
        return _widget_from_json(r.json())

    def get_embed_snippet(self, widget_id: str) -> EmbedSnippet:
        with self._client() as c:
            r = c.get(
                f"/api/v1/admin/widgets/{widget_id}/embed-snippet",
                headers=self._headers(),
            )
        self._raise_for_status(r)
        data = r.json()
        return EmbedSnippet(
            snippet=data["snippet"],
            loader_url=data["loader_url"],
            data_widget_id=data["data_widget_id"],
        )

    # -- allowed origins ---------------------------------------------------

    def list_allowed_origins(self) -> list[AllowedOrigin]:
        with self._client() as c:
            r = c.get("/api/v1/admin/allowed-origins", headers=self._headers())
        self._raise_for_status(r)
        return [
            AllowedOrigin(id=item["id"], origin=item["origin"])
            for item in r.json()
        ]

    def add_allowed_origin(self, origin: str) -> AllowedOrigin:
        with self._client() as c:
            r = c.post(
                "/api/v1/admin/allowed-origins",
                headers=self._headers(),
                json={"origin": origin},
            )
        self._raise_for_status(r)
        data = r.json()
        return AllowedOrigin(id=data["id"], origin=data["origin"])

    def delete_allowed_origin(self, origin_id: str) -> None:
        with self._client() as c:
            r = c.delete(
                f"/api/v1/admin/allowed-origins/{origin_id}",
                headers=self._headers(),
            )
        self._raise_for_status(r)

    # -- guardrail config --------------------------------------------------

    def get_guardrail_config(self) -> dict[str, Any]:
        with self._client() as c:
            r = c.get(
                "/api/v1/admin/guardrail-config", headers=self._headers()
            )
        self._raise_for_status(r)
        return r.json().get("config") or {}

    def put_guardrail_config(self, config: dict[str, Any]) -> dict[str, Any]:
        with self._client() as c:
            r = c.put(
                "/api/v1/admin/guardrail-config",
                headers=self._headers(),
                json={"config": config},
            )
        if r.status_code == 422:
            # Distinguish floor-violation 422 from generic Pydantic 422.
            try:
                body = r.json()
            except ValueError:
                body = {}
            if isinstance(body, dict) and body.get("error") == "floor_violation":
                raise FloorViolationError(
                    key_path=body["key_path"],
                    attempted_value=body.get("attempted_value"),
                    floor_value=body.get("floor_value"),
                )
        self._raise_for_status(r)
        return r.json().get("config") or {}

    # -- signing key -------------------------------------------------------

    def get_signing_key(self) -> SigningKeyMeta | None:
        with self._client() as c:
            r = c.get("/api/v1/admin/signing-key", headers=self._headers())
        self._raise_for_status(r)
        body = r.json()
        if body is None:
            return None
        return SigningKeyMeta(
            version=int(body["version"]), created_at=str(body["created_at"])
        )

    def rotate_signing_key(self) -> SigningKeyMeta:
        with self._client() as c:
            r = c.post(
                "/api/v1/admin/signing-key/rotate", headers=self._headers()
            )
        self._raise_for_status(r)
        body = r.json()
        return SigningKeyMeta(
            version=int(body["version"]), created_at=str(body["created_at"])
        )

    # -- platform (tenant_manager) ----------------------------------------
    #
    # These hit the manager router (mounted at ``/tenants``). The manager
    # legitimately targets tenants by id (path param) — that is the lifecycle
    # power of the role. The "never send a client-supplied tenant_id as scope"
    # rule (FR-031) applies to the tenant_admin self-scope, not here.

    def list_tenants(self, *, limit: int = 200, offset: int = 0) -> list[TenantSummary]:
        with self._client() as c:
            r = c.get(
                "/tenants",
                params={"limit": limit, "offset": offset},
                headers=self._headers(),
            )
        self._raise_for_status(r)
        return [_tenant_from_json(item) for item in r.json()]

    def get_tenant(self, tenant_id: str) -> TenantSummary:
        with self._client() as c:
            r = c.get(f"/tenants/{tenant_id}", headers=self._headers())
        self._raise_for_status(r)
        return _tenant_from_json(r.json())

    def create_tenant(
        self, *, name: str, first_admin_email: str, first_admin_password: str
    ) -> CreatedTenant:
        with self._client() as c:
            r = c.post(
                "/tenants",
                headers=self._headers(),
                json={
                    "name": name,
                    "first_admin_email": first_admin_email,
                    "first_admin_password": first_admin_password,
                },
            )
        self._raise_for_status(r)
        data = r.json()
        return CreatedTenant(
            tenant_id=str(data["tenant_id"]),
            name=data["name"],
            slug=data["slug"],
            status=data["status"],
            first_admin_user_id=str(data["first_admin_user_id"]),
        )

    def suspend_tenant(self, tenant_id: str) -> str:
        with self._client() as c:
            r = c.post(f"/tenants/{tenant_id}/suspend", headers=self._headers())
        self._raise_for_status(r)
        return str(r.json()["status"])

    def reactivate_tenant(self, tenant_id: str) -> str:
        with self._client() as c:
            r = c.post(f"/tenants/{tenant_id}/reactivate", headers=self._headers())
        self._raise_for_status(r)
        return str(r.json()["status"])

    def erase_tenant(self, tenant_id: str) -> dict[str, Any]:
        with self._client() as c:
            r = c.delete(f"/tenants/{tenant_id}", headers=self._headers())
        self._raise_for_status(r)
        return r.json().get("summary") or {}

    def get_tenant_cost(
        self, tenant_id: str, *, since: str | None = None, until: str | None = None
    ) -> TenantCost:
        with self._client() as c:
            r = c.get(
                f"/tenants/{tenant_id}/cost",
                params=_drop_none({"since": since, "until": until}),
                headers=self._headers(),
            )
        self._raise_for_status(r)
        return _tenant_cost_from_json(r.json())

    def get_cost_all(
        self, *, since: str | None = None, until: str | None = None
    ) -> list[TenantCost]:
        with self._client() as c:
            r = c.get(
                "/tenants/cost/all",
                params=_drop_none({"since": since, "until": until}),
                headers=self._headers(),
            )
        self._raise_for_status(r)
        return [_tenant_cost_from_json(item) for item in r.json()]

    def get_cost_series(
        self, *, since: str | None = None, until: str | None = None
    ) -> dict[str, list[CostPoint]]:
        """Batched daily series for ALL tenants, keyed by tenant_id (FR-015).

        One call — never one per row — so the Cost Overview has no N+1 fan-out.
        """
        with self._client() as c:
            r = c.get(
                "/tenants/cost/series",
                params=_drop_none(
                    {"since": since, "until": until, "granularity": "daily"}
                ),
                headers=self._headers(),
            )
        self._raise_for_status(r)
        series: dict[str, list[CostPoint]] = {}
        for item in r.json():
            series[str(item["tenant_id"])] = [
                CostPoint(
                    date=bucket["date"],
                    cost_usd=bucket["cost_usd"],
                    total_tokens=int(bucket["total_tokens"]),
                )
                for bucket in item.get("buckets", [])
            ]
        return series

    def list_audit(
        self, *, limit: int = 50, before_id: str | None = None
    ) -> list[AuditEntry]:
        with self._client() as c:
            r = c.get(
                "/tenants/audit",
                params=_drop_none({"limit": limit, "before_id": before_id}),
                headers=self._headers(),
            )
        self._raise_for_status(r)
        return [_audit_from_json(item) for item in r.json()]

    def create_manager(self, *, email: str, password: str) -> CreatedManager:
        with self._client() as c:
            r = c.post(
                "/tenants/managers",
                headers=self._headers(),
                json={"email": email, "password": password},
            )
        self._raise_for_status(r)
        data = r.json()
        return CreatedManager(
            manager_user_id=str(data["manager_user_id"]), email=data["email"]
        )

    # -- tenant-admin: leads + members -------------------------------------
    #
    # These hit the tenant-admin router (``/api/v1/admin``). The backend
    # derives ``tenant_id`` from the verified JWT, so NONE of these methods
    # accept a ``tenant_id`` argument — the typed signatures enforce FR-031.

    def list_leads(
        self,
        *,
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[LeadRow]:
        with self._client() as c:
            r = c.get(
                "/api/v1/admin/leads",
                params=_drop_none(
                    {"since": since, "until": until, "status": status, "limit": limit}
                ),
                headers=self._headers(),
            )
        self._raise_for_status(r)
        return [_lead_from_json(item) for item in r.json()]

    def list_members(self) -> list[MemberRow]:
        with self._client() as c:
            r = c.get("/api/v1/admin/members", headers=self._headers())
        self._raise_for_status(r)
        return [_member_from_json(item) for item in r.json()]

    def invite_member(self, *, email: str, password: str) -> MemberRow:
        with self._client() as c:
            r = c.post(
                "/api/v1/admin/members",
                headers=self._headers(),
                json={"email": email, "password": password},
            )
        self._raise_for_status(r)
        return _member_from_json(r.json())

    def remove_member(self, user_id: str) -> None:
        with self._client() as c:
            r = c.delete(
                f"/api/v1/admin/members/{user_id}", headers=self._headers()
            )
        self._raise_for_status(r)

    # -- tenant-admin: CMS content (feature 007) ---------------------------
    #
    # Hits the tenant-admin CMS router (``/api/v1/admin/cms``). The backend
    # derives ``tenant_id`` from the verified JWT, so none of these methods
    # accept a ``tenant_id`` argument.

    def list_cms_pages(
        self, *, published: bool | None = None, limit: int = 200
    ) -> list[CmsPageRow]:
        with self._client() as c:
            r = c.get(
                "/api/v1/admin/cms/pages",
                params=_drop_none({"published": published, "limit": limit}),
                headers=self._headers(),
            )
        self._raise_for_status(r)
        return [_cms_page_from_json(item) for item in r.json()]

    def get_cms_page(self, page_id: str) -> CmsPageRow:
        with self._client() as c:
            r = c.get(
                f"/api/v1/admin/cms/pages/{page_id}", headers=self._headers()
            )
        self._raise_for_status(r)
        return _cms_page_from_json(r.json())

    def create_cms_page(
        self,
        *,
        title: str,
        body: str,
        slug: str | None = None,
        is_published: bool = True,
    ) -> CmsPageRow:
        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "is_published": is_published,
        }
        if slug:
            payload["slug"] = slug
        with self._client() as c:
            r = c.post(
                "/api/v1/admin/cms/pages", headers=self._headers(), json=payload
            )
        self._raise_for_status(r)
        return _cms_page_from_json(r.json())

    def update_cms_page(
        self,
        page_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        slug: str | None = None,
        is_published: bool | None = None,
    ) -> CmsPageRow:
        payload = _drop_none(
            {
                "title": title,
                "body": body,
                "slug": slug,
                "is_published": is_published,
            }
        )
        with self._client() as c:
            r = c.put(
                f"/api/v1/admin/cms/pages/{page_id}",
                headers=self._headers(),
                json=payload,
            )
        self._raise_for_status(r)
        return _cms_page_from_json(r.json())

    def delete_cms_page(self, page_id: str) -> None:
        with self._client() as c:
            r = c.delete(
                f"/api/v1/admin/cms/pages/{page_id}", headers=self._headers()
            )
        self._raise_for_status(r)


def _drop_none(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v is not None}


def _tenant_from_json(item: dict[str, Any]) -> TenantSummary:
    return TenantSummary(
        tenant_id=str(item["tenant_id"]),
        name=item["name"],
        slug=item["slug"],
        status=item["status"],
        created_at=str(item.get("created_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
    )


def _tenant_cost_from_json(item: dict[str, Any]) -> TenantCost:
    return TenantCost(
        tenant_id=str(item["tenant_id"]),
        total_events=int(item.get("total_events") or 0),
        total_input_tokens=int(item.get("total_input_tokens") or 0),
        total_output_tokens=int(item.get("total_output_tokens") or 0),
        total_cost_usd=str(item.get("total_cost_usd") or "0"),
    )


def _audit_from_json(item: dict[str, Any]) -> AuditEntry:
    return AuditEntry(
        entry_id=str(item["entry_id"]),
        actor_user_id=str(item["actor_user_id"]) if item.get("actor_user_id") else None,
        actor_email=item.get("actor_email"),
        action=item["action"],
        target_tenant_id=str(item["target_tenant_id"]) if item.get("target_tenant_id") else None,
        target_tenant_slug=item.get("target_tenant_slug"),
        created_at=str(item["created_at"]),
        meta=item.get("meta") or {},
    )


def _lead_from_json(item: dict[str, Any]) -> LeadRow:
    return LeadRow(
        lead_id=str(item["id"]),
        name=item.get("name") or "",
        contact=item.get("contact") or "",
        intent=item.get("intent") or "",
        status=item.get("status") or "new",
        created_at=str(item.get("created_at") or ""),
        conversation_id=str(item["conversation_id"]) if item.get("conversation_id") else None,
    )


def _member_from_json(item: dict[str, Any]) -> MemberRow:
    return MemberRow(
        user_id=str(item["user_id"]),
        email=item.get("email") or "",
        created_at=str(item.get("created_at") or ""),
    )


def _cms_page_from_json(item: dict[str, Any]) -> CmsPageRow:
    return CmsPageRow(
        id=str(item["id"]),
        title=item.get("title") or "",
        slug=item.get("slug") or "",
        body=item.get("body") or "",
        is_published=bool(item.get("is_published", False)),
        created_at=str(item.get("created_at") or ""),
        updated_at=str(item.get("updated_at") or ""),
    )


def _widget_from_json(item: dict[str, Any]) -> AdminWidget:
    return AdminWidget(
        id=item["id"],
        public_widget_id=item["public_widget_id"],
        name=item["name"],
        theme=item.get("theme") or {},
        greeting=item.get("greeting") or "",
        status=item["status"],
    )
