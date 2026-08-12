from fastapi import FastAPI
from sqlalchemy.exc import IntegrityError

from request_engine.entrypoints.http.appointments import create_appointments_router
from request_engine.entrypoints.http.catalog import create_catalog_router
from request_engine.entrypoints.http.errors import (
    booking_error_handler,
    integrity_error_handler,
    queue_error_handler,
    request_error_handler,
)
from request_engine.entrypoints.http.queues import create_queues_router
from request_engine.entrypoints.http.requests import create_requests_router
from request_engine.entrypoints.http.security import ActorResolver
from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.reservation_commands import PostgresReservationCommands
from request_engine.modules.booking.adapters.db.reservation_reader import PostgresReservationReader
from request_engine.modules.booking.application.errors import BookingError
from request_engine.modules.catalog.adapters.db.business_info_reader import PostgresBusinessInfoReader
from request_engine.modules.catalog.adapters.db.offering_catalog_reader import (
    PostgresOfferingCatalogReader,
)
from request_engine.modules.queue.adapters.db.leave_queue_commands import PostgresLeaveQueueCommands
from request_engine.modules.queue.adapters.db.service_queue_catalog_reader import (
    PostgresServiceQueueCatalogReader,
)
from request_engine.modules.queue.adapters.db.service_queue_commands import (
    PostgresServiceQueueCommands,
)
from request_engine.modules.queue.adapters.db.service_queue_reader import PostgresServiceQueueReader
from request_engine.modules.queue.application.errors import QueueError
from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.adapters.db.request_definition_reader import (
    PostgresRequestDefinitionResolver,
)
from request_engine.modules.requests.adapters.db.request_reader import PostgresRequestReader
from request_engine.modules.requests.application.errors import RequestError
from request_engine.platform.db.session import SessionFactory


def create_app(
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> FastAPI:
    """Compose the HTTP process around explicit database and authentication dependencies."""

    app = FastAPI(
        title="Request Engine",
        version="0.1.0",
        description=(
            "Headless customer-operations API. Authentication/tenant authority is supplied "
            "by the deployment ActorResolver; request bodies never select their own tenant."
        ),
    )

    request_commands = PostgresRequestCommands(session_factory)
    request_reader = PostgresRequestReader(session_factory)
    definition_resolver = PostgresRequestDefinitionResolver(session_factory)

    business_reader = PostgresBusinessInfoReader(session_factory)
    offering_reader = PostgresOfferingCatalogReader(session_factory)

    availability_reader = PostgresAppointmentAvailabilityReader(session_factory)
    reservation_commands = PostgresReservationCommands(session_factory)
    reservation_reader = PostgresReservationReader(session_factory)

    queue_commands = PostgresServiceQueueCommands(session_factory)
    leave_queue_commands = PostgresLeaveQueueCommands(session_factory)
    queue_reader = PostgresServiceQueueReader(session_factory)
    queue_catalog_reader = PostgresServiceQueueCatalogReader(session_factory)

    app.add_exception_handler(RequestError, request_error_handler)
    app.add_exception_handler(BookingError, booking_error_handler)
    app.add_exception_handler(QueueError, queue_error_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)

    app.include_router(
        create_requests_router(
            commands=request_commands,
            reader=request_reader,
            definition_resolver=definition_resolver,
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_catalog_router(
            business_reader=business_reader,
            offering_reader=offering_reader,
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_appointments_router(
            availability_reader=availability_reader,
            commands=reservation_commands,
            reservation_reader=reservation_reader,
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_queues_router(
            commands=queue_commands,
            leave_commands=leave_queue_commands,
            reader=queue_reader,
            catalog_reader=queue_catalog_reader,
            actor_resolver=actor_resolver,
        )
    )
    return app
