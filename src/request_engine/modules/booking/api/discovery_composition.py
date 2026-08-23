from request_engine.modules.booking.adapters.discovery_slot_reader import PostgresPublishedSlotReader
from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.platform.db.session import SessionFactory


def build_published_slot_reader(domain_session_factory: SessionFactory) -> PublishedSlotReader:
    """Build the narrow Booking read port used by a trusted discovery gateway.

    The public Discovery app receives only this port and never the underlying
    domain SessionFactory or the normal Booking appointment-option signing key.
    """

    return PostgresPublishedSlotReader(domain_session_factory)
