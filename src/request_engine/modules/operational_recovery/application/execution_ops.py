from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.commands import (
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryIdempotencyConflict,
)
from request_engine.modules.operational_recovery.application.execution_booking import (
    run_booking_execution,
)
from request_engine.modules.operational_recovery.application.execution_policy import (
    affected_reservation,
    raise_rejected,
    require_expected_proposal,
    require_target,
)
from request_engine.modules.operational_recovery.application.fingerprints import (
    execution_fingerprint,
)
from request_engine.modules.operational_recovery.application.notification_ops import (
    ensure_notification,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.proposal_ops import get_proposal
from request_engine.modules.operational_recovery.contracts.models import (
    RecoveryExecution,
    RecoveryExecutionStatus,
)


async def execute_recovery(
    command: ExecuteRecoveryCommand,
    *,
    repository: RecoveryRepository,
    capacity: RecoveryCapacitySource,
    booking: RecoveryBookingPort,
    communications: RecoveryCommunicationPort,
) -> RecoveryExecution:
    if not command.idempotency_key:
        raise ValueError("idempotency_key is required")
    proposal = await get_proposal(
        repository=repository,
        organization_id=command.organization_id,
        proposal_id=command.proposal_id,
    )
    require_expected_proposal(command, proposal)
    affected = affected_reservation(proposal, command.reservation_id)
    target = require_target(affected)
    fingerprint = execution_fingerprint(command, target)
    record = await repository.prepare_execution(
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        idempotency_key=command.idempotency_key,
        command_fingerprint=fingerprint,
        proposal=proposal,
        reservation_id=command.reservation_id,
        notification_requested=command.notify,
    )
    execution = record.execution
    if (
        execution.proposal_id != command.proposal_id
        or execution.reservation_id != command.reservation_id
        or record.command_fingerprint != fingerprint
    ):
        raise RecoveryIdempotencyConflict()
    if execution.status is RecoveryExecutionStatus.REJECTED:
        raise_rejected(execution)
    if execution.status is RecoveryExecutionStatus.PREPARED:
        execution = await run_booking_execution(
            command=command,
            proposal=proposal,
            affected=affected,
            execution=execution,
            newly_prepared=record.created,
            capacity=capacity,
            booking=booking,
            repository=repository,
        )
    if command.notify and execution.notification.communication_task_id is None:
        execution = await ensure_notification(
            command=command,
            affected=affected,
            execution=execution,
            communications=communications,
            repository=repository,
        )
    return execution
