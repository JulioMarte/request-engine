from uuid import UUID


class BookingError(Exception):
    """Base class for semantic booking failures."""


class BookingConfigurationError(BookingError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class OfferingVersionNotBookable(BookingError):
    def __init__(self, offering_version_id: UUID) -> None:
        super().__init__(f"OfferingVersion {offering_version_id} is not bookable")
        self.offering_version_id = offering_version_id


class OfferingVersionNotFound(BookingError):
    def __init__(self, offering_version_id: UUID) -> None:
        super().__init__(f"OfferingVersion {offering_version_id} was not found")
        self.offering_version_id = offering_version_id


class InvalidResourceSelection(BookingError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AppointmentUnavailable(BookingError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class ReservationNotFound(BookingError):
    def __init__(self, reservation_id: UUID) -> None:
        super().__init__(f"Reservation {reservation_id} was not found")
        self.reservation_id = reservation_id


class ReservationNotCancellable(BookingError):
    def __init__(self, reservation_id: UUID, status: str) -> None:
        super().__init__(f"Reservation {reservation_id} cannot be cancelled from status {status}")
        self.reservation_id = reservation_id
        self.status = status
