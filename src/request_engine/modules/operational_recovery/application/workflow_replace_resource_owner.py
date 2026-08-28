from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
)
from request_engine.modules.booking.contracts.recovery import (
    RecoveryTargetUnavailable as BookingRecoveryTargetUnavailable,
)
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ReplaceResourceRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_reschedule_request import (
    workflow_booking_request,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryTarget,
    RescheduleProposal,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
)


async def execute_booking_replace_resource_step(
    *,
    command: ReplaceResourceRecoveryActionCommand,
    action: RecoveryAction,
    proposal: RescheduleProposal,
    affected: AffectedReservation,
    target: RecoveryTarget,
    repository: RecoveryWorkflowRepository,
    booking: RecoveryBookingPort,
) -> Reservation:
    try:
        return await booking.reschedule_for_recovery(
            workflow_booking_request(
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                idempotency_key=f"recovery-action:{action.id}:booking-replace-resource:v1",
                allow_subject_override=command.allow_subject_override,
                proposal=proposal,
                affected=affected,
                target=target,
            )
        )
    except RecoveryBookingConflict as exc:
        await reject_replace_resource_action(
            repository, command, action, "STALE_RECOVERY_PROPOSAL"
        )
        raise StaleRecoveryProposal() from exc
    except BookingRecoveryTargetUnavailable as exc:
        await reject_replace_resource_action(
            repository, command, action, "RECOVERY_TARGET_UNAVAILABLE"
        )
        raise RecoveryTargetUnavailable(command.reservation_id, str(exc)) from exc


async def reject_replace_resource_action(
    repository: RecoveryWorkflowRepository,
    command: ReplaceResourceRecoveryActionCommand,
    action: RecoveryAction,
    failure_code: str,
) -> None:
    await repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=action.status,
        status=RecoveryActionStatus.REJECTED,
        failure_code=failure_code,
    )
