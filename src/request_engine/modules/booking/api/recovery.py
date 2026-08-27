from request_engine.modules.booking.adapters.db.recovery_port import PostgresRecoveryBookingPort
from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.platform.db.session import SessionFactory


def build_recovery_booking_port(session_factory: SessionFactory) -> RecoveryBookingPort:
    return PostgresRecoveryBookingPort(session_factory)
