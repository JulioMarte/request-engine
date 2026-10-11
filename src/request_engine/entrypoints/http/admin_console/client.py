"""Thin server-to-server HTTP client for the platform control plane.

The console never re-implements control-plane authority. It forwards the
operator's single stored bearer (or the short-lived setup bearer) and returns the
raw status/payload so the UI can render the exact machine-readable envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from request_engine.entrypoints.http.admin_console.json_types import as_mapping

_JSON_HEADERS = {"accept": "application/json"}


@dataclass(frozen=True)
class ControlResponse:
    """A control-plane response with its status, JSON payload and headers."""

    status_code: int
    payload: Any
    headers: dict[str, str]

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def error_body(self) -> dict[str, Any] | None:
        if self.ok:
            return None
        error = as_mapping(self.payload).get("error")
        if isinstance(error, dict):
            return as_mapping(error)
        return None

    @property
    def error_code(self) -> str | None:
        body = self.error_body
        code = body.get("code") if body is not None else None
        return code if isinstance(code, str) else None

    @property
    def error_detail(self) -> dict[str, Any]:
        body = self.error_body
        details = body.get("details") if body is not None else None
        return as_mapping(details)

    @property
    def retry_after_seconds(self) -> int | None:
        raw = self.headers.get("retry-after")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None


class ControlPlanePort(Protocol):
    """Structural boundary so the console can be composed with a substitute client."""

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        setup_bearer: str | None = None,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ControlResponse: ...

    async def openapi(self) -> dict[str, Any]: ...

    async def aclose(self) -> None: ...


class ControlPlaneClient:
    """Async wrapper around the control-plane HTTP API."""

    def __init__(self, *, base_url: str, timeout_seconds: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        bearer: str | None = None,
        setup_bearer: str | None = None,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ControlResponse:
        headers = dict(_JSON_HEADERS)
        if bearer is not None:
            headers["authorization"] = f"Bearer {bearer}"
        elif setup_bearer is not None:
            headers["authorization"] = f"Setup {setup_bearer}"
        if extra_headers is not None:
            headers.update(extra_headers)
        response = await self._client.request(
            method,
            path,
            json=json_body,
            params=params,
            headers=headers,
        )
        try:
            payload: Any = response.json()
        except ValueError:
            payload = response.text
        return ControlResponse(
            status_code=response.status_code,
            payload=payload,
            headers={key.lower(): value for key, value in response.headers.items()},
        )

    async def openapi(self) -> dict[str, Any]:
        response = await self._client.get(
            "/openapi.json",
            headers={"accept": "application/json", "cache-control": "no-cache"},
        )
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict):
            raise RuntimeError("control-plane OpenAPI document is not an object")
        return as_mapping(document)


__all__ = ["ControlPlaneClient", "ControlPlanePort", "ControlResponse"]
