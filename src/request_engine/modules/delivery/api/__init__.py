from fastapi import FastAPI

from request_engine.modules.delivery.adapters.db.live_service_operations import (
    PostgresLiveServiceOperations,
)
from request_engine.modules.delivery.adapters.db.service_session_reader import (
    PostgresServiceSessionReader,
)
from request_engine.modules.delivery.api.live_errors import live_service_error_handler
from request_engine.modules.delivery.api.live_router import create_live_service_router
from request_engine.modules.delivery.application.errors import LiveServiceError
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Install F3 live execution; ReservationAccess remains unchanged."""

    app.add_exception_handler(LiveServiceError, live_service_error_handler)
    app.include_router(
        create_live_service_router(
            operations=PostgresLiveServiceOperations(session_factory),
            reader=PostgresServiceSessionReader(session_factory),
            actor_resolver=actor_resolver,
        )
    )
