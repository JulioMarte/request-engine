from request_engine.modules.booking.adapters.db.onboarding_reader import (
    PostgresBookingOnboardingReader,
)
from request_engine.modules.booking.contracts.onboarding import BookingOnboardingReadinessReader
from request_engine.platform.db.session import SessionFactory


def build_onboarding_booking_reader(
    session_factory: SessionFactory,
) -> BookingOnboardingReadinessReader:
    return PostgresBookingOnboardingReader(session_factory)
