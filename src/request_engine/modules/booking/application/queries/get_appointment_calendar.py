"""Appointment calendar Query: Reservations overlapping a bounded window.

Same authority as the day board (``appointments.day_board``): the calendar is a
longer window over the same operator reservation facts, plus the claimed
Resources and the offering name. Rows are ordered by ``(start_at,
reservation_id)``; ``after`` continues strictly after that position.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointment_calendar import AppointmentCalendarPage

MAX_CALENDAR_WINDOW = timedelta(days=42)
MAX_CALENDAR_LIMIT = 200


@dataclass(frozen=True, slots=True)
class CalendarPosition:
    start_at: datetime
    reservation_id: UUID


@dataclass(frozen=True, slots=True)
class AppointmentCalendarQuery:
    organization_id: UUID
    window_start: datetime
    window_end: datetime
    location_id: UUID | None
    resource_id: UUID | None
    after: CalendarPosition | None
    limit: int


class AppointmentCalendarReader(Protocol):
    async def read_calendar(self, query: AppointmentCalendarQuery) -> AppointmentCalendarPage: ...


def validate_calendar_window(window_start: datetime, window_end: datetime) -> None:
    if window_start.utcoffset() is None or window_end.utcoffset() is None:
        raise ValueError("calendar window timestamps must include a timezone offset")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    if window_end - window_start > MAX_CALENDAR_WINDOW:
        raise ValueError("calendar window cannot exceed 42 days")
