from uuid import UUID

from request_engine.modules.booking.domain.errors import (
    BookingConfigurationError as BookingConfigurationError,
)
from request_engine.modules.booking.domain.errors import BookingError


class OfferingVersionNotBookable(BookingError):
    def __init__(self, offering_version_id: UUID) -> None:
        super().__init__(f"OfferingVersion {offering_version_id} is not bookable")
        self.offering_version_id = offering_version_id


class OfferingVersionNotFound(BookingError):
    def __init__(self, offering_version_id: UUID) -> None:
        super().__init__(f"OfferingVersion {offering_version_id} was not found")
        self.offering_version_id = offering_version_id


class AppointmentOptionInvalid(BookingError):
    def __init__(self, reason: str) -> None:
        super().__init__(f"AppointmentOption is invalid: {reason}")
        self.reason = reason


class AppointmentOptionExpired(BookingError):
    def __init__(self) -> None:
        super().__init__("AppointmentOption has expired")


class AppointmentOptionStale(BookingError):
    def __init__(self, reason: str = "material booking configuration changed") -> None:
        super().__init__("AppointmentOption is stale")
        self.reason = reason


class InvalidResourceSelection(BookingError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AppointmentUnavailable(BookingError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SubjectAuthorityRequired(BookingError):
    def __init__(self, subject_party_id: UUID, scope_key: str) -> None:
        super().__init__(
            f"Principal is not authorized to act for Party {subject_party_id} in scope {scope_key}"
        )
        self.subject_party_id = subject_party_id
        self.scope_key = scope_key


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


class CapacityHoldRevisionConflict(BookingError):
    def __init__(self, hold_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"CapacityHold {hold_id} revision conflict: expected {expected}, current {actual}"
        )
        self.hold_id = hold_id
        self.expected = expected
        self.actual = actual


class ReservationNotFound(BookingError):
    def __init__(self, reservation_id: UUID) -> None:
        super().__init__(f"Reservation {reservation_id} was not found")
        self.reservation_id = reservation_id


class ReservationRevisionConflict(BookingError):
    def __init__(self, reservation_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Reservation {reservation_id} revision conflict: expected {expected}, current {actual}"
        )
        self.reservation_id = reservation_id
        self.expected = expected
        self.actual = actual


class ReservationNotConfirmed(BookingError):
    def __init__(self, reservation_id: UUID, status: str) -> None:
        super().__init__(
            f"Reservation {reservation_id} is not confirmed for this operation: {status}"
        )
        self.reservation_id = reservation_id
        self.status = status


class ArrivalEstimateInvalid(BookingError):
    def __init__(self, reservation_id: UUID, reason: str) -> None:
        super().__init__(f"Reservation {reservation_id} arrival estimate is invalid: {reason}")
        self.reservation_id = reservation_id
        self.reason = reason


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


ReservationStateConflict = (
    ReservationNotConfirmed | ReservationNotCancellable | ReservationNotReschedulable
)
