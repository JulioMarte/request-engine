from sqlalchemy.exc import DBAPIError

from request_engine.modules.booking.application.commands.book_appointment import (
    BookAppointmentCommand,
    BookAppointmentHandler,
)
from request_engine.modules.booking.application.errors import AppointmentOptionStale
from request_engine.modules.booking.contracts.appointments import Reservation


class DiscoverySafeBookAppointmentHandler:
    def __init__(self, delegate: BookAppointmentHandler) -> None:
        self._delegate = delegate

    async def book_appointment(self, command: BookAppointmentCommand) -> Reservation:
        try:
            return await self._delegate.book_appointment(command)
        except DBAPIError as exc:
            if _is_discovery_stale(exc):
                raise AppointmentOptionStale("discovery publication or mapping changed") from None
            raise


def _is_discovery_stale(exc: DBAPIError) -> bool:
    if getattr(exc.orig, "sqlstate", None) != "40001":
        return False
    message = str(exc.orig).lower()
    return "discovery option stale" in message
