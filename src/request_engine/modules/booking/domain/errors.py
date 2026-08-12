class BookingError(Exception):
    """Base class for semantic Booking failures."""


class BookingConfigurationError(BookingError):
    """Raised when versioned booking policy/configuration is invalid."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
