from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.lifecycle import ReservationLifecycleSnapshot


class ReservationLifecycleNotificationPort(Protocol):
    async def reconcile_reservation_notifications(
        self,
        snapshot: ReservationLifecycleSnapshot,
        *,
        source_event_id: UUID,
    ) -> None: ...

    async def cancel_reservation_notifications(
        self,
        organization_id: UUID,
        reservation_id: UUID,
    ) -> None: ...
