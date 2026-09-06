from uuid import UUID

from request_engine.modules.operational_recovery.application.commands import ExecuteRecoveryCommand
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryReservationNotAffected,
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryExecution,
    RecoveryTarget,
    RescheduleProposal,
)

STALE_FAILURE = "STALE_RECOVERY_PROPOSAL"
TARGET_FAILURE = "RECOVERY_TARGET_UNAVAILABLE"


def require_expected_proposal(
    command: ExecuteRecoveryCommand,
    proposal: RescheduleProposal,
) -> None:
    if (
        command.expected_source_fingerprint != proposal.source_fingerprint
        or command.expected_proposal_fingerprint != proposal.proposal_fingerprint
    ):
        raise StaleRecoveryProposal()


def affected_reservation(
    proposal: RescheduleProposal,
    reservation_id: UUID,
) -> AffectedReservation:
    result = next(
        (item for item in proposal.affected if item.reservation_id == reservation_id),
        None,
    )
    if result is None:
        raise RecoveryReservationNotAffected(reservation_id)
    return result


def require_target(affected: AffectedReservation) -> RecoveryTarget:
    if affected.target is None:
        raise RecoveryTargetUnavailable(affected.reservation_id)
    return affected.target


def raise_rejected(execution: RecoveryExecution) -> None:
    if execution.failure_code == STALE_FAILURE:
        raise StaleRecoveryProposal()
    if execution.failure_code == TARGET_FAILURE:
        raise RecoveryTargetUnavailable(execution.reservation_id)
    raise RuntimeError(f"unknown recovery rejection code: {execution.failure_code}")
