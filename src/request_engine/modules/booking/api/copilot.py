from request_engine.modules.booking.adapters.db.copilot_reader import (
    PostgresCopilotBookingReader,
)
from request_engine.modules.booking.contracts.copilot import CopilotBookingReader
from request_engine.platform.db.session import SessionFactory


def build_copilot_booking_reader(session_factory: SessionFactory) -> CopilotBookingReader:
    return PostgresCopilotBookingReader(session_factory)
