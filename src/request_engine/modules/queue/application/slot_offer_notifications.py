from datetime import datetime
from typing import Protocol
from uuid import UUID


class SlotOfferNotificationPort(Protocol):
    """Durably record notification intent inside the caller transaction.

    Implementations may persist communications state, but must not perform provider
    network I/O before the surrounding authoritative transaction commits.
    """

    async def create_slot_offer_notification(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        recipient_party_id: UUID,
        slot_offer_id: UUID,
        slot_opportunity_id: UUID,
        start_at: datetime,
        end_at: datetime,
        expires_at: datetime,
    ) -> UUID: ...

    async def cancel_slot_offer_notification(
        self,
        transaction: object,
        *,
        organization_id: UUID,
        slot_offer_id: UUID,
    ) -> None: ...
