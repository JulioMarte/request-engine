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
    build_internal_discovery_slot_reader,
)
from request_engine.modules.booking.api.discovery_gateway import (
    create_discovery_availability_router,
)
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

_CORRELATION_HEADER = "X-Correlation-ID"


async def _request_context(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    correlation_id = request_correlation_id(request)
    response = await call_next(request)
    response.headers[_CORRELATION_HEADER] = str(correlation_id)
    return response


def create_discovery_availability_app(
    *,
    domain_session_factory: SessionFactory,
    actor_resolver: PlatformDiscoveryActorResolver,
) -> FastAPI:
    """Internal Booking process that owns tenant-domain read credentials."""

    app = FastAPI(
        title="Request Engine Discovery Availability Gateway",
        version="0.1.0",
        description="Internal publication-fenced access to authoritative Booking availability.",
    )
    app.middleware("http")(_request_context)
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.include_router(
        create_discovery_availability_router(
            slot_reader=build_internal_discovery_slot_reader(domain_session_factory),
            actor_resolver=RequestPlatformDiscoveryActorResolver(actor_resolver),
        )
    )
    return app
