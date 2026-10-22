from fastapi import FastAPI

from request_engine.modules.booking.adapters.db.appointment_calendar_reader import (
    PostgresAppointmentCalendarReader,
)
from request_engine.modules.booking.adapters.db.day_board_reader import (
    PostgresReservationDayBoardReader,
)
from request_engine.modules.booking.api.appointment_calendar_router import (
    create_appointment_calendar_router,
)
from request_engine.modules.booking.api.day_board_router import create_day_board_router
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.http import ActorResolver


def install_day_board_http(
    app: FastAPI,
    *,
    session_factory: SessionFactory,
    actor_resolver: ActorResolver,
) -> None:
    """Install the operator reservation reads (day board and calendar).

    Both static ``/v1/appointments/...`` paths are registered before the
    ``/v1/appointments/{reservation_id}`` routes so they are matched first.
    """

    app.include_router(
        create_day_board_router(PostgresReservationDayBoardReader(session_factory), actor_resolver)
    )
    app.include_router(
        create_appointment_calendar_router(
            PostgresAppointmentCalendarReader(session_factory), actor_resolver
        )
    )
