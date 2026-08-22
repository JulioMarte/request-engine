import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
    http_exception_handler,
    request_validation_error_handler,
)
from request_engine.modules.booking.api.discovery_composition import (
    build_appointment_option_codec,
    build_published_slot_reader,
)
from request_engine.modules.discovery.api import install_http
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import (
    AuthenticationRequired,
    CapabilityRequired,
    request_correlation_id,
)
from request_engine.platform.security.platform_discovery import (
    PlatformDiscoveryActorResolver,
    RequestPlatformDiscoveryActorResolver,
)

_APPOINTMENT_OPTION_SIGNING_KEY_ENV = "REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY"
_CORRELATION_HEADER = "X-Correlation-ID"


async def _request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    correlation_id = request_correlation_id(request)
    response = await call_next(request)
    response.headers[_CORRELATION_HEADER] = str(correlation_id)
    return response


def create_discovery_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: PlatformDiscoveryActorResolver,
    appointment_option_signing_key: bytes | None = None,
) -> FastAPI:
    signing_key = appointment_option_signing_key
    if signing_key is None:
        configured_key = os.environ.get(_APPOINTMENT_OPTION_SIGNING_KEY_ENV)
        if configured_key is None:
            raise RuntimeError(f"{_APPOINTMENT_OPTION_SIGNING_KEY_ENV} must be configured")
        signing_key = configured_key.encode("utf-8")
    app = FastAPI(
        title="Request Engine Discovery",
        version="0.1.0",
        description="Least-privilege cross-tenant discovery over explicitly published supply.",
    )
    app.middleware("http")(_request_context)
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    install_http(
        app,
        session_factory=session_factory,
        actor_resolver=RequestPlatformDiscoveryActorResolver(actor_resolver),
        slot_reader=build_published_slot_reader(session_factory),
        option_codec=build_appointment_option_codec(signing_key),
    )
    return app
