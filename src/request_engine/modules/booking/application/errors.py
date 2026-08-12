from uuid import UUID

from request_engine.modules.booking.domain.errors import (
    BookingConfigurationError,
    BookingError,
)


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


class InvalidHoldExpiration(BookingError):
    def __init__(self) -> None:
        super().__init__("CapacityHold expires_at must be after the database wall-clock time")


class CapacityHoldNotFound(BookingError):
    def __init__(self, hold_id: UUID) -> None:
        super().__init__(f"CapacityHold {hold_id} was not found")
        self.hold_id = hold_id


class CapacityHoldNotActive(BookingError):
    def __init__(self, hold_id: UUID, status: str) -> None:
        super().__init__(f"CapacityHold {hold_id} is not active: {status}")
        self.hold_id = hold_id
        self.status = status


class CapacityHoldExpired(BookingError):
    def __init__(self, hold_id: UUID) -> None:
        super().__init__(f"CapacityHold {hold_id} has expired")
        self.hold_id = hold_id


class ReservationNotFound(BookingError):
    def __init__(self, reservation_id: UUID) -> None:
        super().__init__(f"Reservation {reservation_id} was not found")
        self.reservation_id = reservation_id


class ReservationNotCancellable(BookingError):
    def __init__(self, reservation_id: UUID, status: str) -> None:
        super().__init__(f"Reservation {reservation_id} cannot be cancelled from status {status}")
        self.reservation_id = reservation_id
        self.status = status


class ReservationNotReschedulable(BookingError):
    def __init__(self, reservation_id: UUID, status: str) -> None:
        super().__init__(f"Reservation {reservation_id} cannot be rescheduled from status {status}")
        self.reservation_id = reservation_id
        self.status = status
