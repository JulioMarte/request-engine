import os

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import IntegrityError

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
from request_engine.modules.queue.api import install_http as install_queue_http
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.modules.tenancy.api import build_party_authority_reader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.security.http import (
    ActorResolver,
    AuthenticationRequired,
    CapabilityRequired,
)

_APPOINTMENT_OPTION_SIGNING_KEY_ENV = "REQUEST_ENGINE_APPOINTMENT_OPTION_SIGNING_KEY"


def create_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    appointment_option_signing_key: bytes | None = None,
) -> FastAPI:
    """Compose module-owned HTTP surfaces around platform dependencies."""

    signing_key = appointment_option_signing_key
    if signing_key is None:
        configured_key = os.environ.get(_APPOINTMENT_OPTION_SIGNING_KEY_ENV)
        if configured_key is None:
            raise RuntimeError(
                f"{_APPOINTMENT_OPTION_SIGNING_KEY_ENV} must be configured when no signing key "
                "is supplied explicitly"
            )
        signing_key = configured_key.encode("utf-8")

    app = FastAPI(
        title="Request Engine",
        version="0.1.0",
        description=(
            "Headless customer-operations API. Authentication/tenant authority is supplied "
            "by the deployment ActorResolver; request bodies never select their own tenant."
        ),
    )
    app.add_exception_handler(AuthenticationRequired, authentication_required_handler)
    app.add_exception_handler(CapabilityRequired, capability_required_handler)
    app.add_exception_handler(IdempotencyConflict, idempotency_conflict_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    party_authority_reader = build_party_authority_reader(session_factory)

    install_requests_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_catalog_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    install_booking_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
        party_authority_reader=party_authority_reader,
        appointment_option_signing_key=signing_key,
    )
    install_queue_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    return app
