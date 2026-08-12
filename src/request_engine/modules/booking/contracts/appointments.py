from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class ReservationStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class AttendanceStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"


@dataclass(frozen=True, slots=True)
class ResourceChoice:
    requirement_id: UUID
    resource_id: UUID


@dataclass(frozen=True, slots=True)
class AppointmentSlot:
    offering_version_id: UUID
    start_at: datetime
    end_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]


@dataclass(frozen=True, slots=True)
class Reservation:
    id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: ReservationStatus
    revision: int
    attendance_status: AttendanceStatus = AttendanceStatus.PENDING
