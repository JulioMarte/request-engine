from uuid import UUID


class AttendanceError(Exception):
    """Base error for attendance lifecycle commands."""


class AttendanceReservationNotActive(AttendanceError):
    def __init__(self, reservation_id: UUID, status: str) -> None:
        super().__init__(f"Reservation {reservation_id} is not active for attendance: {status}")


class AttendanceRevisionConflict(AttendanceError):
    def __init__(self, reservation_id: UUID, expected: int, actual: int) -> None:
        super().__init__(
            f"Reservation {reservation_id} revision conflict: expected {expected}, actual {actual}"
        )


class AttendanceOutcomeConflict(AttendanceError):
    def __init__(self, reservation_id: UUID, status: str) -> None:
        super().__init__(f"Reservation {reservation_id} already has attendance outcome {status}")


class NoShowEvaluationTooEarly(AttendanceError):
    def __init__(self, reservation_id: UUID) -> None:
        super().__init__(f"Reservation {reservation_id} no-show cutoff has not been reached")
