"""FIFO service queue and released-slot recovery capability."""

from request_engine.modules.booking.contracts.slot_offer_capacity import SlotOfferCapacityPort
from request_engine.modules.queue.adapters.db.slot_offer_commands import PostgresSlotOfferCommands
from request_engine.modules.queue.application.slot_offer_notifications import (
    SlotOfferNotificationPort,
)
from request_engine.platform.db.session import SessionFactory


def build_slot_offer_commands(
    session_factory: SessionFactory,
    *,
    capacity: SlotOfferCapacityPort,
    notification: SlotOfferNotificationPort,
) -> PostgresSlotOfferCommands:
    """Compose queue-owned SlotOffer orchestration from explicit outbound ports."""
    return PostgresSlotOfferCommands(
        session_factory,
        capacity=capacity,
        notification=notification,
    )
