"""Transactional communications and reminder capability module."""

from request_engine.modules.communications.adapters.db.slot_offer_intent import (
    PostgresSlotOfferNotificationIntent,
)


def build_slot_offer_notification_intent() -> PostgresSlotOfferNotificationIntent:
    """Build the communications-owned adapter used by queue composition."""
    return PostgresSlotOfferNotificationIntent()
