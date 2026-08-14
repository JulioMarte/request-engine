import os
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.capabilities import create_capability_router
from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
    http_exception_handler,
    idempotency_conflict_handler,
    integrity_error_handler,
    request_validation_error_handler,
)
from request_engine.modules.booking.api import install_http as install_booking_http
from request_engine.modules.catalog.api import install_http as install_catalog_http
from request_engine.modules.communications.api import install_http as install_communications_http
from request_engine.modules.queue.api import QueueSlotOfferHttpPorts
from request_engine.modules.queue.api import install_http as install_queue_http
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.modules.tenancy.api import build_party_authority_reader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.discovery import (
    BaselineTenantCapabilityPolicy,
    TenantCapabilityPolicy,
)
from request_engine.platform.security.execution_context import clear_actor_context
from request_engine.platform.security.http import (
    ActorResolver,
    AuthenticationRequired,
    CapabilityRequired,
    RequestExecutionActorResolver,
    TenantCapabilityActorResolver,
    request_correlation_id,
)

_APPOINTMENT_OPTION_SIGNING_KEY_ENV = "REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY"
_CORRELATION_HEADER = "X-Correlation-ID"


def create_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    slot_offer_ports: QueueSlotOfferHttpPorts | None = None,
    appointment_option_signing_key: bytes | None = None,
    tenant_capability_policy: TenantCapabilityPolicy | None = None,
) -> FastAPI:
    """Compose module-owned HTTP surfaces around explicit external ports."""

    signing_key = appointment_option_signing_key
    if signing_key is None:
        configured_key = os.environ.get(_APPOINTMENT_OPTION_SIGNING_KEY_ENV)
        if configured_key is None:
            raise RuntimeError(
                f"{_APPOINTMENT_OPTION_SIGNING_KEY_ENV} must be configured when no signing key "
                "is supplied explicitly"
            )
        signing_key = configured_key.encode("utf-8")

    policy = tenant_capability_policy or BaselineTenantCapabilityPolicy()
    request_actor_resolver = RequestExecutionActorResolver(actor_resolver)
    execution_actor_resolver = TenantCapabilityActorResolver(request_actor_resolver, policy)

    app = FastAPI(
        title="Request Engine",
        version="0.1.0",
        description=(
            "Headless customer-operations API. Authentication/tenant authority is supplied "
            "by the deployment ActorResolver; request bodies never select their own tenant."
        ),
    )

    @app.middleware("http")
    async def request_execution_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        correlation_id = request_correlation_id(request)
        try:
            response = await call_next(request)
            response.headers[_CORRELATION_HEADER] = str(correlation_id)
            return response
        finally:
            clear_actor_context()

    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    party_authority_reader = build_party_authority_reader(session_factory)

    app.include_router(
        create_capability_router(
            actor_resolver=request_actor_resolver,
            tenant_capability_policy=policy,
        )
    )
    install_requests_http(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
    )
    install_catalog_http(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
    )
    install_booking_http(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
        party_authority_reader=party_authority_reader,
        appointment_option_signing_key=signing_key,
    )
    install_queue_http(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
        slot_offer_ports=slot_offer_ports,
    )
    install_communications_http(
        app,
        session_factory=session_factory,
        actor_resolver=execution_actor_resolver,
    )
    return app
