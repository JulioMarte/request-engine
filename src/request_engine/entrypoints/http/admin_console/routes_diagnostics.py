"""Diagnostics routes: redacted operational state for debugging.

Requires an authenticated console session. Shows counters, configuration summary
and the recent error ring with request ids, so a failing browser flow can be
correlated with a structured log line. Never exposes secrets.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from request_engine.entrypoints.http.admin_console.state import AdminConsoleState


def _config_summary(state: AdminConsoleState) -> dict[str, Any]:
    settings = state.settings
    return {
        "control_api_base_url": settings.control_api_base_url,
        "session_cookie_name": settings.session_cookie_name,
        "setup_cookie_name": settings.setup_cookie_name,
        "cookie_secure": settings.cookie_secure,
        "cookie_samesite": settings.cookie_samesite,
        "session_ttl_seconds": settings.session_ttl_seconds,
        "setup_ttl_seconds": settings.setup_ttl_seconds,
        "request_timeout_seconds": settings.request_timeout_seconds,
        "openapi_cache_seconds": settings.openapi_cache_seconds,
        "log_level": settings.log_level,
        "debug": settings.debug,
    }


def install_diagnostics_routes(app: FastAPI, state: AdminConsoleState) -> None:
    async def _operation_count() -> int | None:
        try:
            catalog = await state.catalog()
        except Exception:
            return None
        return len(catalog.operations)

    async def diagnostics_page(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return RedirectResponse("/login", status_code=303)
        return state.templates.TemplateResponse(
            request,
            "diagnostics.html",
            state.context(
                request,
                request_id=getattr(request.state, "request_id", ""),
                metrics=state.metrics.snapshot(),
                errors=[asdict(event) for event in state.errors.recent(50)],
                error_total=state.errors.total(),
                config=_config_summary(state),
                operation_count=await _operation_count(),
            ),
        )

    async def diagnostics_errors(request: Request) -> Response:
        session = state.session(request)
        if session is None:
            return JSONResponse({"error": "authentication required"}, status_code=401)
        return JSONResponse(
            {
                "metrics": state.metrics.snapshot(),
                "errors": [asdict(event) for event in state.errors.recent(100)],
            }
        )

    app.add_api_route(
        "/diagnostics", diagnostics_page, methods=["GET"], response_class=HTMLResponse
    )
    app.add_api_route("/diagnostics/errors.json", diagnostics_errors, methods=["GET"])


__all__ = ["install_diagnostics_routes"]
