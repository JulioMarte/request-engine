from fastapi import FastAPI

from request_engine.modules.booking.adapters.appointment_options import (
    SignedAppointmentOptionCodec,
)
from request_engine.modules.booking.adapters.db.appointment_availability_reader import (
    PostgresAppointmentAvailabilityReader,
)
from request_engine.modules.booking.adapters.db.attendance_commands import (
    PostgresAttendanceCommands,
)
from request_engine.modules.booking.adapters.db.capacity_error_boundary import (
    CapacitySafeBookingCommitmentCommands,
    CapacitySafeReservationCommands,
)
from request_engine.modules.booking.adapters.db.contextual_config_commands import (
    PostgresContextualConfigCommands,
)
from request_engine.modules.booking.adapters.db.contextual_supply_lifecycle_commands import (
    PostgresContextualSupplyLifecycleCommands,
)
from request_engine.modules.booking.adapters.db.contextual_terms_supersession_commands import (
    PostgresContextualTermsSupersessionCommands,
)
from request_engine.modules.booking.adapters.db.reservation_reader import (
    PostgresReservationReader,
)
from request_engine.modules.booking.adapters.db.resource_schedule_exception_commands import (
    PostgresResourceScheduleExceptionCommands,
)
from request_engine.modules.booking.api.errors import booking_error_handler
from request_engine.modules.booking.api.operational_assignment_router import (
    create_operational_assignment_router,
)
from request_engine.modules.booking.api.operational_errors import (
    booking_operational_error_handler,
)
from request_engine.modules.booking.api.operational_exception_router import (
    create_operational_exception_router,
)
from request_engine.modules.booking.api.operational_terms_router import (
    create_operational_terms_router,
)
from request_engine.modules.booking.api.router import create_router
from request_engine.modules.booking.application.errors import BookingError
from request_engine.modules.booking.application.operational_errors import (
    ContextualConfigurationConflict,
    ResourceAvailabilityRevisionConflict,
    ResourceLocationAssignmentRevisionConflict,
)
from request_engine.modules.tenancy.contracts.authority import PartyAuthorityReader
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
    party_authority_reader: PartyAuthorityReader,
    appointment_option_signing_key: bytes,
) -> None:
    """Connect the public Booking HTTP surface."""

    reservations = CapacitySafeReservationCommands(session_factory)
    commitments = CapacitySafeBookingCommitmentCommands(session_factory)
    app.add_exception_handler(BookingError, booking_error_handler)
    app.include_router(
        create_router(
            availability_reader=PostgresAppointmentAvailabilityReader(session_factory),
            option_codec=SignedAppointmentOptionCodec(appointment_option_signing_key),
            book_handler=reservations,
            cancel_handler=reservations,
            reschedule_handler=commitments,
            attendance_handler=PostgresAttendanceCommands(session_factory),
            reservation_reader=PostgresReservationReader(session_factory),
            authority_reader=party_authority_reader,
            actor_resolver=actor_resolver,
        )
    )


def install_operational_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Connect Booking configuration commands to the operator HTTP process."""

    for error_type in (
        ResourceAvailabilityRevisionConflict,
        ResourceLocationAssignmentRevisionConflict,
        ContextualConfigurationConflict,
    ):
        app.add_exception_handler(error_type, booking_operational_error_handler)
    config = PostgresContextualConfigCommands(session_factory)
    lifecycle = PostgresContextualSupplyLifecycleCommands(session_factory)
    app.include_router(
        create_operational_assignment_router(
            assign_handler=config,
            retire_handler=lifecycle,
            availability_handler=lifecycle,
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_operational_exception_router(
            assignment_handler=lifecycle,
            resource_handler=PostgresResourceScheduleExceptionCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
    app.include_router(
        create_operational_terms_router(
            configure_handler=config,
            supersede_handler=PostgresContextualTermsSupersessionCommands(session_factory),
            actor_resolver=actor_resolver,
        )
    )
