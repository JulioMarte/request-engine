from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    Reservation,
    ResourceChoice,
)


class ResourceChoiceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement_id: UUID
    resource_id: UUID

    def to_contract(self) -> ResourceChoice:
        return ResourceChoice(requirement_id=self.requirement_id, resource_id=self.resource_id)


class AppointmentSlotView(BaseModel):
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoiceModel, ...]

    @classmethod
    def from_contract(cls, slot: AppointmentSlot) -> "AppointmentSlotView":
        return cls(
            offering_version_id=slot.offering_version_id,
            start_at=slot.start_at,
            end_at=slot.end_at,
            location_id=slot.location_id,
            resources=tuple(
                ResourceChoiceModel(
                    requirement_id=item.requirement_id,
                    resource_id=item.resource_id,
                )
                for item in slot.resources
            ),
        )


class BookAppointmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    offering_version_id: UUID
    subject_party_id: UUID
    start_at: datetime
    resources: tuple[ResourceChoiceModel, ...] = Field(min_length=1, max_length=20)
    location_id: UUID | None = None
    origin_request_id: UUID | None = None


class CancelReservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(gt=0)
    reason: str | None = Field(default=None, max_length=1000)


class RescheduleReservationBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_at: datetime
    resources: tuple[ResourceChoiceModel, ...] = Field(min_length=1, max_length=20)
    expected_revision: int = Field(gt=0)
    location_id: UUID | None = None


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
