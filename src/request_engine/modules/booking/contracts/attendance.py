from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import AttendanceStatus


class AttendanceOutcomeStatus(StrEnum):
    PENDING = "pending"
    CHECKED_IN = "checked_in"
    NO_SHOW = "no_show"


@dataclass(frozen=True, slots=True)
class ReservationAttendanceState:
    reservation_id: UUID
    reservation_revision: int
    response_status: AttendanceStatus
    outcome_status: AttendanceOutcomeStatus
    response_id: UUID | None = None
    responded_at: datetime | None = None
    checked_in_at: datetime | None = None
    no_show_at: datetime | None = None
