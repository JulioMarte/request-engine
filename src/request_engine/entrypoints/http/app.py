from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.errors import (
    authentication_required_handler,
    capability_required_handler,
    integrity_error_handler,
)
from request_engine.modules.booking.api import install_http as install_booking_http
from request_engine.modules.catalog.api import install_http as install_catalog_http
from request_engine.modules.queue.api import install_http as install_queue_http
from request_engine.modules.requests.api import install_http as install_requests_http
from request_engine.modules.tenancy.api import build_party_authority_reader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import (
    ActorResolver,
    AuthenticationRequired,
    CapabilityRequired,
)


def create_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> FastAPI:
    """Compose module-owned HTTP surfaces around platform dependencies."""

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
    )
    install_queue_http(
        app,
        session_factory=session_factory,
        actor_resolver=actor_resolver,
    )
    return app
