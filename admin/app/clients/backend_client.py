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


def _widget_from_json(item: dict[str, Any]) -> AdminWidget:
    return AdminWidget(
        id=item["id"],
        public_widget_id=item["public_widget_id"],
        name=item["name"],
        theme=item.get("theme") or {},
        greeting=item.get("greeting") or "",
        status=item["status"],
    )
