from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ReservationNotificationPlan:
    confirmation: bool
    reminders_before_minutes: tuple[int, ...]
    attendance_confirmation_required: bool
    attendance_request_before_minutes: int | None
    channel_policy: dict[str, object]


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
    no_show_after_minutes: int | None
    notification_plan: ReservationNotificationPlan


@dataclass(frozen=True, slots=True)
class ReleasedReservationSlot:
    organization_id: UUID
    reservation_id: UUID
    offering_version_id: UUID
    location_id: UUID | None
    start_at: datetime
    end_at: datetime
    recovery_enabled: bool
    minimum_lead_minutes: int


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
