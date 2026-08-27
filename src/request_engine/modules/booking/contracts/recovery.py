from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.appointments import (
    AppointmentSlot,
    Reservation,
    ResourceChoice,
)


class RecoveryBookingConflict(Exception):
    pass


class RecoveryTargetUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryRescheduleRequest:
    organization_id: UUID
    principal_id: UUID
    reservation_id: UUID
    expected_revision: int
    start_at: datetime
    location_id: UUID | None
    resources: tuple[ResourceChoice, ...]
    source_resource_id: UUID
    expected_source_resource_availability_revision: int
    source_location_id: UUID
    expected_source_location_operational_revision: int
    idempotency_key: str
    allow_subject_override: bool


class RecoveryBookingPort(Protocol):
    async def get_reservation(
        self, *, organization_id: UUID, reservation_id: UUID
    ) -> Reservation | None: ...

    async def find_recovery_slots(
        self,
        *,
        organization_id: UUID,
        offering_version_id: UUID,
        window_start: datetime,
        window_end: datetime,
        location_id: UUID | None,
        limit: int,
    ) -> tuple[AppointmentSlot, ...]: ...

    async def reschedule_for_recovery(
        self, request: RecoveryRescheduleRequest
    ) -> Reservation: ...
