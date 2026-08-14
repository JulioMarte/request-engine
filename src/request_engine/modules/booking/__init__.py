"""Local appointment booking and capacity authority."""

from request_engine.modules.booking.adapters.db.slot_offer_capacity import PostgresSlotOfferCapacity


def build_slot_offer_capacity() -> PostgresSlotOfferCapacity:
    """Build the booking-owned port used by released-slot recovery."""
    return PostgresSlotOfferCapacity()
