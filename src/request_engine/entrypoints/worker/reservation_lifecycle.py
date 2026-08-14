from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from request_engine.modules.booking.contracts.lifecycle import (
    ReservationLifecycleReader,
    ReservationLifecycleSchedulingPort,
)
from request_engine.modules.communications.contracts.reservation_lifecycle import (
    ReservationLifecycleNotificationPort,
)
from request_engine.modules.queue.contracts.released_slot_recovery import ReleasedSlotRecoveryPort

ReservationEventType = Literal[
    "reservation.created.v1",
    "reservation.rescheduled.v1",
    "reservation.cancelled.v1",
]


@dataclass(frozen=True, slots=True)
class ReservationLifecycleEvent:
    event_id: UUID
    organization_id: UUID
    reservation_id: UUID
    event_type: ReservationEventType


async def handle_reservation_lifecycle_event(
    event: ReservationLifecycleEvent,
    *,
    worker_principal_id: UUID,
    reader: ReservationLifecycleReader,
    scheduling: ReservationLifecycleSchedulingPort,
    notifications: ReservationLifecycleNotificationPort,
    recovery: ReleasedSlotRecoveryPort,
) -> None:
    snapshot = await reader.get_lifecycle_snapshot(event.organization_id, event.reservation_id)
    if snapshot is None:
        return

    if event.event_type == "reservation.cancelled.v1":
        await scheduling.cancel_reservation_schedule(event.organization_id, event.reservation_id)
        await notifications.cancel_reservation_notifications(
            event.organization_id, event.reservation_id
        )
    else:
        await scheduling.reconcile_reservation_schedule(snapshot, source_event_id=event.event_id)
        await notifications.reconcile_reservation_notifications(
            snapshot, source_event_id=event.event_id
        )

    if event.event_type in {"reservation.cancelled.v1", "reservation.rescheduled.v1"}:
        slot = await reader.get_released_slot(
            event.organization_id,
            event.reservation_id,
            event_type=event.event_type,
        )
        if slot is not None:
            await recovery.recover_released_slot(
                slot,
                source_event_id=event.event_id,
                principal_id=worker_principal_id,
            )
