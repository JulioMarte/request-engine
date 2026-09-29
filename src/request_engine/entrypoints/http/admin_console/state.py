"""Shared web state for the admin console routes.

Holds the settings, the control-plane client, the template engine and the
OpenAPI catalog cache, plus the cookie session helpers used by every route.
"""

from __future__ import annotations

import hmac
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast

from fastapi import Request, Response
from fastapi.templating import Jinja2Templates

from request_engine.entrypoints.http.admin_console.catalog import AdminCatalog, load_catalog
from request_engine.entrypoints.http.admin_console.client import ControlPlanePort, ControlResponse
from request_engine.entrypoints.http.admin_console.observability import (
    ConsoleMetrics,
    ErrorEvent,
    ErrorTracker,
    configure_logging,
)
from request_engine.entrypoints.http.admin_console.session import (
    AdminSession,
    decode_session,
    decode_value,
    encode_session,
    encode_value,
    new_csrf_token,
)
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings

_SameSite = Literal["lax", "strict", "none"]


@dataclass(frozen=True)
class SetupState:
    """Short-lived first-run setup bearer, held only in a signed cookie."""

    token: str
    csrf: str
    expires_at: int


class AdminConsoleState:
    """Composition state shared by the console route installers."""

    def __init__(
        self,
        *,
        settings: AdminConsoleSettings,
        control: ControlPlanePort,
        runtime: ControlPlanePort | None,
        templates: Jinja2Templates,
    ) -> None:
        self.settings = settings
        self.control = control
        self.runtime = runtime
        self.templates = templates
        self.logger = configure_logging(settings.log_level)
        self.errors = ErrorTracker()
        self.metrics = ConsoleMetrics()
        self._secret = settings.session_secret.get_secret_value().encode("utf-8")
        self._catalog: AdminCatalog | None = None
        self._catalog_at = 0.0
        self._runtime_catalog: AdminCatalog | None = None
        self._runtime_catalog_at = 0.0

    @property
    def secret(self) -> bytes:
        return self._secret

    def session(self, request: Request) -> AdminSession | None:
        raw = request.cookies.get(self.settings.session_cookie_name)
        if raw is None:
            return None
        return decode_session(self._secret, raw)

    def setup(self, request: Request) -> SetupState | None:
        raw = request.cookies.get(self.settings.setup_cookie_name)
        if raw is None:
            return None
        payload = decode_value(self._secret, raw)
        if payload is None:
            return None
        token = payload.get("t")
        csrf = payload.get("c")
        expires_at = payload.get("e")
        if not isinstance(token, str) or not isinstance(csrf, str):
            return None
        if not isinstance(expires_at, int):
            return None
        if expires_at <= int(time.time()):
            return None
        return SetupState(token=token, csrf=csrf, expires_at=expires_at)

    def attach_session(self, response: Response, session: AdminSession) -> None:
        response.set_cookie(
            self.settings.session_cookie_name,
            encode_session(self._secret, session),
            max_age=self.settings.session_ttl_seconds,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite=cast(_SameSite, self.settings.cookie_samesite),
            path="/",
        )

    def clear_session(self, response: Response) -> None:
        response.delete_cookie(self.settings.session_cookie_name, path="/")

    def attach_setup(self, response: Response, token: str) -> str:
        csrf = new_csrf_token()
        setup = SetupState(
            token=token,
            csrf=csrf,
            expires_at=int(time.time()) + self.settings.setup_ttl_seconds,
        )
        response.set_cookie(
            self.settings.setup_cookie_name,
            encode_value(
                self._secret,
                {"t": setup.token, "c": setup.csrf, "e": setup.expires_at},
            ),
            max_age=self.settings.setup_ttl_seconds,
            httponly=True,
            secure=self.settings.cookie_secure,
            samesite=cast(_SameSite, self.settings.cookie_samesite),
            path="/",
        )
        return csrf

    def clear_setup(self, response: Response) -> None:
        response.delete_cookie(self.settings.setup_cookie_name, path="/")

    def csrf_matches(self, submitted: str | None, expected: str | None) -> bool:
        if not submitted or not expected:
            return False
        return hmac.compare_digest(submitted, expected)

    async def catalog(self) -> AdminCatalog:
        now = time.monotonic()
        if (
            self._catalog is not None
            and now - self._catalog_at < self.settings.openapi_cache_seconds
        ):
            return self._catalog
        try:
            document = await self.control.openapi()
        except Exception as exc:
            self.logger.error(
                "openapi fetch failed",
                extra={"extra_fields": {"error_type": type(exc).__name__, "error": str(exc)}},
            )
            raise
        self._catalog = load_catalog(document)
        self._catalog_at = now
        self.logger.info(
            "catalog loaded",
            extra={"extra_fields": {"operations": len(self._catalog.operations)}},
        )
        return self._catalog

    async def control_request(
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
        """Forward one control-plane call with timing, logging and redaction."""

        started = time.monotonic()
        try:
            response = await self.control.request(
                method,
                path,
                bearer=bearer,
                setup_bearer=setup_bearer,
                json_body=json_body,
                params=params,
                extra_headers=extra_headers,
            )
        except Exception as exc:
            self.metrics.observe_control_call(error=True)
            self.logger.error(
                "control call failed",
                extra={
                    "extra_fields": {
                        "control_method": method,
                        "control_path": path,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                },
            )
            raise
        duration_ms = round((time.monotonic() - started) * 1000, 1)
        self.metrics.observe_control_call(error=not response.ok)
        fields: dict[str, object] = {
            "control_method": method,
            "control_path": path,
            "control_status": response.status_code,
            "duration_ms": duration_ms,
        }
        if response.ok:
            self.logger.info("control call", extra={"extra_fields": fields})
        else:
            fields["control_error_code"] = response.error_code
            self.logger.warning("control call rejected", extra={"extra_fields": fields})
        return response

    async def runtime_catalog(self) -> AdminCatalog:
        if self.runtime is None:
            raise RuntimeError("runtime API is not configured")
        now = time.monotonic()
        if (
            self._runtime_catalog is not None
            and now - self._runtime_catalog_at < self.settings.openapi_cache_seconds
        ):
            return self._runtime_catalog
        self._runtime_catalog = load_catalog(await self.runtime.openapi())
        self._runtime_catalog_at = now
        return self._runtime_catalog

    async def runtime_request(
        self,
        method: str,
        path: str,
        *,
        organization_id: str,
        bearer: str | None,
        json_body: object | None = None,
        params: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> ControlResponse:
        if self.runtime is None:
            raise RuntimeError("runtime API is not configured")
        headers = dict(extra_headers or {})
        headers["X-RE-Organization-ID"] = organization_id
        return await self.runtime.request(
            method, path, bearer=bearer, json_body=json_body, params=params, extra_headers=headers
        )

    def record_error(
        self,
        *,
        request_id: str,
        kind: str,
        message: str,
        method: str = "",
        path: str = "",
        status: int | None = None,
        detail: str | None = None,
    ) -> None:
        self.errors.record(
            ErrorEvent(
                at=datetime.now(UTC).isoformat(),
                request_id=request_id,
                kind=kind,
                message=message,
                method=method,
                path=path,
                status=status,
                detail=detail,
            )
        )

    def context(self, request: Request, **extra: Any) -> dict[str, Any]:
        session = self.session(request)
        base: dict[str, Any] = {
            "request": request,
            "authenticated": session is not None,
            "csrf_token": session.csrf_token if session is not None else "",
            "control_base_url": self.settings.control_api_base_url,
            "current_path": request.url.path,
            "current_year": datetime.now(UTC).year,
        }
        base.update(extra)
        return base


__all__ = ["AdminConsoleState", "SetupState"]
