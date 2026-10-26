from fastapi import FastAPI

from request_engine.modules.booking.adapters.db.resource_configuration_commands import (
    PostgresResourceConfigurationCommands,
)
from request_engine.modules.booking.api.operational_errors import booking_operational_error_handler
from request_engine.modules.booking.api.resource_configuration_router import (
    create_resource_configuration_router,
)
from request_engine.modules.booking.application.operational_errors import ResourceCapabilityHeld
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_resource_configuration_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Install Resource rename and capability-set replacement (operator process)."""

    app.add_exception_handler(ResourceCapabilityHeld, booking_operational_error_handler)
    commands = PostgresResourceConfigurationCommands(session_factory)
    app.include_router(
        create_resource_configuration_router(
            update_handler=commands,
            capabilities_handler=commands,
            actor_resolver=actor_resolver,
        )
    )
