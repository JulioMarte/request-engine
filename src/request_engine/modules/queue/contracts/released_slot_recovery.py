from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.lifecycle import ReleasedReservationSlot
from request_engine.modules.queue.contracts.waitlist import SlotOffer, SlotOpportunity


class ReleasedSlotRecoveryPort(Protocol):
    async def recover_released_slot(
        self,
        slot: ReleasedReservationSlot,
        *,
        source_event_id: UUID,
        principal_id: UUID,
    ) -> tuple[SlotOpportunity, SlotOffer | None] | None: ...
