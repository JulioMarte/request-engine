from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.booking.contracts.appointments import AppointmentSlot, Reservation
from request_engine.modules.booking.contracts.attendance import ReservationAttendanceState


class AppointmentSlotView(BaseModel):
    option_id: str
    start_at: datetime
    end_at: datetime
    location_id: UUID | None

    @classmethod
    def from_contract(cls, slot: AppointmentSlot, *, option_id: str) -> "AppointmentSlotView":
        return cls(
            option_id=option_id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            location_id=slot.location_id,
        )


class BookAppointmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str = Field(min_length=1, max_length=8192)
    subject_party_id: UUID
    origin_request_id: UUID | None = None


class CancelReservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class RescheduleReservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    option_id: str = Field(min_length=1, max_length=8192)
    expected_revision: int = Field(gt=0)


class AttendanceResponseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: Literal["accepted", "declined"]
    expected_revision: int = Field(gt=0)


class AttendanceStateView(BaseModel):
    reservation_id: UUID
    reservation_revision: int
    response_status: str
    outcome_status: str
    responded_at: datetime | None
    checked_in_at: datetime | None
    no_show_at: datetime | None

    @classmethod
    def from_contract(cls, state: ReservationAttendanceState) -> "AttendanceStateView":
        return cls(
            reservation_id=state.reservation_id,
            reservation_revision=state.reservation_revision,
            response_status=state.response_status.value,
            outcome_status=state.outcome_status.value,
            responded_at=state.responded_at,
            checked_in_at=state.checked_in_at,
            no_show_at=state.no_show_at,
        )


class ReservationView(BaseModel):
    id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    attendance_status: str

    @classmethod
    def from_contract(cls, reservation: Reservation) -> "ReservationView":
        return cls(
            id=reservation.id,
            offering_version_id=reservation.offering_version_id,
            subject_party_id=reservation.subject_party_id,
            location_id=reservation.location_id,
            start_at=reservation.start_at,
            end_at=reservation.end_at,
            status=reservation.status.value,
            revision=reservation.revision,
            attendance_status=reservation.attendance_status.value,
        )
