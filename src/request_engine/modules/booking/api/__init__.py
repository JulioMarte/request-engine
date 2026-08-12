from fastapi import FastAPI

from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.commitment_commands import (
    PostgresBookingCommitmentCommands,
)
from request_engine.modules.booking.adapters.db.reservation_commands import (
    PostgresReservationCommands,
)
from request_engine.modules.booking.adapters.db.reservation_reader import PostgresReservationReader
from request_engine.modules.booking.api.errors import booking_error_handler
from request_engine.modules.booking.api.router import create_router
from request_engine.modules.booking.application.errors import BookingError
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    party_authority_reader: PartyAuthorityReader,
) -> None:
    """Connect the Booking module to the HTTP process through its owned surface."""

    reservation_commands = PostgresReservationCommands(session_factory)
    commitment_commands = PostgresBookingCommitmentCommands(session_factory)
    app.add_exception_handler(BookingError, booking_error_handler)
    app.include_router(
        create_router(
            availability_reader=PostgresAppointmentAvailabilityReader(session_factory),
            book_handler=reservation_commands,
            cancel_handler=reservation_commands,
            reschedule_handler=commitment_commands,
            reservation_reader=PostgresReservationReader(session_factory),
            authority_reader=party_authority_reader,
            actor_resolver=actor_resolver,
        )
    )
