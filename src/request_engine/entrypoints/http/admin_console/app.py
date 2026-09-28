"""Admin console application factory.

A separate private HTTP entrypoint that composes the auth, setup and operations
routers over a single control-plane client. It owns no business logic: every
action is a control-plane HTTP call, so capabilities and step-up remain the
authority and there is no second execution path.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic
from traceback import format_exc
from uuid import uuid4

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from request_engine.entrypoints.http.admin_console.client import (
    ControlPlaneClient,
    ControlPlanePort,
)
from request_engine.entrypoints.http.admin_console.routes_auth import install_auth_routes
from request_engine.entrypoints.http.admin_console.routes_diagnostics import (
    install_diagnostics_routes,
)
from request_engine.entrypoints.http.admin_console.routes_operations import (
    install_operation_routes,
)
from request_engine.entrypoints.http.admin_console.routes_resources import (
    install_resource_routes,
)
from request_engine.entrypoints.http.admin_console.routes_setup import install_setup_routes
from request_engine.entrypoints.http.admin_console.settings import AdminConsoleSettings
from request_engine.entrypoints.http.admin_console.state import AdminConsoleState

_CONTENT_SECURITY_POLICY = (
    "default-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'"
)


def create_admin_console_app(
    settings: AdminConsoleSettings,
    *,
    client: ControlPlanePort | None = None,
) -> FastAPI:
    """Build the private admin console app around a control-plane client."""

    owns_client = client is None
    control = client or ControlPlaneClient(
        base_url=settings.control_api_base_url,
        timeout_seconds=settings.request_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
        try:
            yield
        finally:
            if owns_client:
                await control.aclose()

    app = FastAPI(
        title="Request Engine admin console",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )
    state = AdminConsoleState(settings=settings, control=control, templates=templates)

    async def observability(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or uuid4().hex[:16]
        request.state.request_id = request_id
        started = monotonic()
        try:
            response = await call_next(request)
        except Exception as exc:
            state.metrics.observe_request(error=True)
            state.record_error(
                request_id=request_id,
                kind="unhandled_exception",
                message=str(exc),
                method=request.method,
                path=request.url.path,
                status=500,
                detail=format_exc() if settings.debug else None,
            )
            state.logger.error(
                "unhandled request exception",
                extra={
                    "extra_fields": {
                        "request_id": request_id,
                        "method": request.method,
                        "path": request.url.path,
                        "error_type": type(exc).__name__,
                    }
                },
                exc_info=exc,
            )
            response = state.templates.TemplateResponse(
                request,
                "error.html",
                state.context(
                    request,
                    request_id=request_id,
                    detail=format_exc() if settings.debug else None,
                ),
                status_code=500,
            )
        else:
            state.metrics.observe_request(error=response.status_code >= 500)
        duration_ms = round((monotonic() - started) * 1000, 1)
        state.logger.info(
            "request",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                }
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=observability)

    async def security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
        return response

    app.add_middleware(BaseHTTPMiddleware, dispatch=security_headers)

    async def live() -> dict[str, str]:
        return {"status": "live"}

    async def ready() -> Response:
        try:
            response = await control.request("GET", "/health/live")
        except httpx.HTTPError:
            return JSONResponse(
                {"status": "unready", "reason": "control_unreachable"}, status_code=503
            )
        if response.status_code != 200:
            return JSONResponse(
                {"status": "unready", "reason": f"control_{response.status_code}"},
                status_code=503,
            )
        return JSONResponse({"status": "ready"})

    app.add_api_route("/health/live", live, methods=["GET"], include_in_schema=False)
    app.add_api_route("/health/ready", ready, methods=["GET"], include_in_schema=False)

    install_auth_routes(app, state)
    install_setup_routes(app, state)
    install_operation_routes(app, state)
    install_resource_routes(app, state)
    install_diagnostics_routes(app, state)
    return app


__all__ = ["create_admin_console_app"]
