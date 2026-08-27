from uuid import UUID


class OperationalRecoveryError(Exception):
    pass


class RecoveryShortfallNotMaterial(OperationalRecoveryError):
    pass


class RecoveryProposalNotFound(OperationalRecoveryError):
    def __init__(self, proposal_id: UUID) -> None:
        self.proposal_id = proposal_id
        super().__init__(f"recovery proposal {proposal_id} was not found")


class RecoveryReservationNotAffected(OperationalRecoveryError):
    def __init__(self, reservation_id: UUID) -> None:
        self.reservation_id = reservation_id
        super().__init__(f"Reservation {reservation_id} is not affected by this proposal")


class RecoveryTargetUnavailable(OperationalRecoveryError):
    def __init__(self, reservation_id: UUID, reason: str | None = None) -> None:
        self.reservation_id = reservation_id
        self.reason = reason
        super().__init__(reason or f"recovery target for Reservation {reservation_id} is unavailable")


class StaleRecoveryProposal(OperationalRecoveryError):
    pass


class RecoveryIdempotencyConflict(OperationalRecoveryError):
    pass
