from request_engine.modules.booking.adapters.discovery_slot_reader import (
    PostgresPublishedSlotReader,
)
from request_engine.modules.booking.contracts.discovery import PublishedSlotReader
from request_engine.platform.db.session import SessionFactory


def build_internal_discovery_slot_reader(
    domain_session_factory: SessionFactory,
) -> PublishedSlotReader:
    """Build the Booking reader for the internal availability gateway process.

    The returned object closes over request_engine_app credentials and therefore
    must never be injected directly into the public Discovery process.
    """

    return PostgresPublishedSlotReader(domain_session_factory)
