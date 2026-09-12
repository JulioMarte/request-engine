from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import FastAPI, Request, Response

from request_engine.entrypoints.http.error_handlers import add_global_error_handlers
from request_engine.entrypoints.http.native_auth import create_native_auth_router
from request_engine.entrypoints.http.native_runtime import build_native_auth_runtime
from request_engine.modules.tenancy.api.native_platform_provisioning import (
    install_native_platform_provisioning_http,
)
from request_engine.platform.db.session import SessionFactory


def create_platform_control_app(
    *,
    auth_session_factory: SessionFactory,
    platform_read_session_factory: SessionFactory,
    platform_write_session_factory: SessionFactory,
    native_authority_id: UUID,
) -> FastAPI:
    """Explicit private control-plane composition; caller owns pool lifecycles.

    No tenant business router or external identity service is required. The
    ordinary native API factory never installs this separate control-plane API.
    """
    runtime = build_native_auth_runtime(
        auth_session_factory, platform_session_factory=platform_read_session_factory
    )
    if runtime.platform_actor_resolver is None:
        raise RuntimeError("Platform control requires an explicit authority read connection")
    app = FastAPI(title="Request Engine platform control", version="1.0.0")

    async def uncached_control_response(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.middleware("http")(uncached_control_response)
    add_global_error_handlers(app)
    app.include_router(
        create_native_auth_router(
            service=runtime.service,
            authenticator=runtime.authenticator,
            identity_authority_id=native_authority_id,
        )
    )
    install_native_platform_provisioning_http(
        app,
        session_factory=platform_write_session_factory,
        actor_resolver=runtime.platform_actor_resolver,
        native_authority_id=native_authority_id,
    )
    return app
