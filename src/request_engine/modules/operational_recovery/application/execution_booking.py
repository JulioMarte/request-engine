from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
)
from request_engine.modules.booking.contracts.recovery import (
    RecoveryTargetUnavailable as BookingRecoveryTargetUnavailable,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.commands import ExecuteRecoveryCommand
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
)
from request_engine.modules.operational_recovery.application.execution_booking_request import (
    booking_request,
)
from request_engine.modules.operational_recovery.application.execution_policy import (
    STALE_FAILURE,
    TARGET_FAILURE,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoveryExecution,
    RescheduleProposal,
)


async def run_booking_execution(
    *,
    command: ExecuteRecoveryCommand,
    proposal: RescheduleProposal,
    affected: AffectedReservation,
    execution: RecoveryExecution,
    newly_prepared: bool,
    capacity: RecoveryCapacitySource,
    booking: RecoveryBookingPort,
    repository: RecoveryRepository,
) -> RecoveryExecution:
    # Early rejection only. Booking's in-transaction revision lock is the
    # authoritative freshness boundary. PREPARED retries skip preflight so
    # Booking idempotency can replay a mutation that already committed.
    if newly_prepared:
        await _validate_source(command, proposal, execution, capacity, repository)
    try:
        result = await booking.reschedule_for_recovery(
            booking_request(command, proposal, affected, execution)
        )
    except RecoveryBookingConflict as exc:
        await _reject(repository, command, execution, STALE_FAILURE)
        raise StaleRecoveryProposal() from exc
    except BookingRecoveryTargetUnavailable as exc:
        await _reject(repository, command, execution, TARGET_FAILURE)
        raise RecoveryTargetUnavailable(command.reservation_id, str(exc)) from exc
    return await repository.succeed_execution(
        organization_id=command.organization_id,
        execution_id=execution.id,
        resulting_revision=result.revision,
    )


async def _validate_source(
    command: ExecuteRecoveryCommand,
    proposal: RescheduleProposal,
    execution: RecoveryExecution,
    capacity: RecoveryCapacitySource,
    repository: RecoveryRepository,
) -> None:
    current = await capacity.assess_recovery_capacity(
        organization_id=command.organization_id,
        service_queue_id=proposal.service_queue_id,
    )
    current_revision = current.checkpoint.recovery_source_revision
    proposal_revision = proposal.source_checkpoint.recovery_source_revision
    if current_revision == proposal_revision:
        return
    await _reject(repository, command, execution, STALE_FAILURE)
    raise StaleRecoveryProposal()


async def _reject(
    repository: RecoveryRepository,
    command: ExecuteRecoveryCommand,
    execution: RecoveryExecution,
    failure_code: str,
) -> None:
    await repository.reject_execution(
        organization_id=command.organization_id,
        execution_id=execution.id,
        failure_code=failure_code,
    )
