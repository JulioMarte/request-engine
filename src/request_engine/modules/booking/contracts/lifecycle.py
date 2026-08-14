from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReservationLifecycleSnapshot:
    organization_id: UUID
    reservation_id: UUID
    offering_version_id: UUID
    subject_party_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    status: str
    revision: int
    booking_policy_snapshot: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReleasedReservationSlot:
    organization_id: UUID
    reservation_id: UUID
    offering_version_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    booking_policy_snapshot: dict[str, object]


class ReservationLifecycleReader(Protocol):
    async def get_lifecycle_snapshot(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> ReservationLifecycleSnapshot | None: ...

    async def get_released_slot(
        self,
        organization_id: UUID,
        reservation_id: UUID,
        *,
        event_type: str,
    ) -> ReleasedReservationSlot | None: ...


class ReservationLifecycleSchedulingPort(Protocol):
    async def reconcile_reservation_schedule(
        self,
        snapshot: ReservationLifecycleSnapshot,
        *,
        source_event_id: UUID,
    ) -> None: ...

    async def cancel_reservation_schedule(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> None: ...
