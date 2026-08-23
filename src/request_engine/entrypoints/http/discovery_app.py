from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
    http_exception_handler,
    request_validation_error_handler,
)
from request_engine.modules.discovery.api import (
    DiscoveryCandidateReader,
    DiscoveryHandoffIssuer,
    RemotePublishedSlotReader,
    install_http,
)
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


def create_discovery_app(
    *,
    candidate_reader: DiscoveryCandidateReader,
    slot_reader: RemotePublishedSlotReader,
    handoff_issuer: DiscoveryHandoffIssuer,
    actor_resolver: PlatformDiscoveryActorResolver,
) -> FastAPI:
    """Compose the public Discovery process from remote/least-privilege ports only."""

    if getattr(slot_reader, "trust_boundary", None) != "remote":
        raise RuntimeError("public Discovery requires a remote Booking availability boundary")
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
        candidate_reader=candidate_reader,
        actor_resolver=RequestPlatformDiscoveryActorResolver(actor_resolver),
        slot_reader=slot_reader,
        handoff_issuer=handoff_issuer,
    )
    return app
