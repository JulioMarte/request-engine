from uuid import UUID

from request_engine.modules.booking.contracts.recovery import RecoveryBookingPort
from request_engine.modules.communications.contracts.recovery import RecoveryCommunicationPort
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
)
from request_engine.modules.operational_recovery.application.notification_ops import (
    autonomous_rescheduled_request,
)
from request_engine.modules.operational_recovery.application.ports import RecoveryRepository
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.application.workflow_reschedule_action import (
    execute_reschedule_action,
)
from request_engine.modules.operational_recovery.application.workflow_reschedule_support import (
    autonomous_reschedule_command,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RescheduleProposal,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryActionConflict,
    RecoveryIncidentStale,
)

_REJECTIONS = (
    RecoveryTargetUnavailable,
    StaleRecoveryProposal,
    RecoveryIncidentStale,
    RecoveryActionConflict,
)


async def execute_autonomy_plan(
    *,
    organization_id: UUID,
    incident_id: UUID,
    proposal: RescheduleProposal,
    source_revision: int,
    plan: tuple[tuple[AffectedReservation, str], ...],
    principal_id: UUID,
    workflow_repository: RecoveryWorkflowRepository,
    proposal_repository: RecoveryRepository,
    booking: RecoveryBookingPort,
    capacity: RecoveryCapacitySource,
    communications: RecoveryCommunicationPort,
) -> None:
    """Run the envelope-approved reschedule work item by item.

    Each item reuses the operator reschedule command semantics, so autonomous
    execution is recorded as the same durable RecoveryAction an operator would
    produce. A business rejection is durable in that action and stops only that
    item; infrastructure failures propagate to the scheduled-action retry.
    """

    for affected, key in plan:
        try:
            await execute_reschedule_action(
                autonomous_reschedule_command(
                    organization_id=organization_id,
                    incident_id=incident_id,
                    proposal=proposal,
                    source_revision=source_revision,
                    affected=affected,
                    principal_id=principal_id,
                    key=key,
                ),
                workflow_repository=workflow_repository,
                proposal_repository=proposal_repository,
                booking=booking,
                capacity=capacity,
            )
        except _REJECTIONS:
            continue
        await communications.create_recovery_notification(
            autonomous_rescheduled_request(
                organization_id=organization_id,
                principal_id=principal_id,
                execution_id=incident_id,
                source_revision=source_revision,
                affected=affected,
            )
        )
