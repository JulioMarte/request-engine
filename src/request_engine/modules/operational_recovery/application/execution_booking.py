from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
    RecoveryCommitmentCheckpoint as BookingCommitmentCheckpoint,
    RecoveryRescheduleRequest,
    RecoveryTargetUnavailable as BookingRecoveryTargetUnavailable,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.commands import ExecuteRecoveryCommand
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
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
    if newly_prepared:
        await _validate_source(command, proposal, execution, capacity, repository)
    target = affected.target
    if target is None:
        raise RuntimeError("prepared recovery execution is missing target")
    try:
        result = await booking.reschedule_for_recovery(
            RecoveryRescheduleRequest(
                organization_id=command.organization_id,
                principal_id=command.principal_id,
                reservation_id=command.reservation_id,
                expected_revision=affected.expected_revision,
                start_at=target.start_at,
                location_id=target.location_id,
                resources=target.resources,
                source_resource_id=proposal.resource_id,
                expected_source_resource_availability_revision=(
                    proposal.source_checkpoint.resource_availability_revision
                ),
                source_location_id=proposal.location_id,
                expected_source_location_operational_revision=(
                    proposal.source_checkpoint.location_operational_revision
                ),
                source_observed_at=proposal.observed_at,
                source_horizon_end=proposal.horizon_end,
                expected_source_commitments=tuple(
                    BookingCommitmentCheckpoint(
                        reservation_id=item.reservation_id,
                        revision=item.revision,
                        starts_at=item.starts_at,
                        ends_at=item.ends_at,
                    )
                    for item in proposal.source_checkpoint.commitments
                ),
                idempotency_key=f"recovery:{execution.id}:booking:v1",
                allow_subject_override=command.allow_subject_override,
            )
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


async def _validate_source(command, proposal, execution, capacity, repository) -> None:
    current = await capacity.assess_recovery_capacity(
        organization_id=command.organization_id,
        service_queue_id=proposal.service_queue_id,
    )
    if current.source_fingerprint == proposal.source_fingerprint:
        return
    await _reject(repository, command, execution, STALE_FAILURE)
    raise StaleRecoveryProposal()


async def _reject(repository, command, execution, failure_code: str) -> None:
    await repository.reject_execution(
        organization_id=command.organization_id,
        execution_id=execution.id,
        failure_code=failure_code,
    )
