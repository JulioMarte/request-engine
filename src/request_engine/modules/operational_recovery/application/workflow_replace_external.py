"""Two-boundary cross-Organization replacement saga (contract 32 section 11).

The new commitment is secured in the provider Organization through the
discovery handoff fence first; the degraded source commitment is disposed
only afterwards, inside the requester Organization. Each boundary is its own
idempotent transaction; replay of the same action resumes the saga instead of
repeating a boundary effect.
"""

from request_engine.modules.booking.contracts.appointments import Reservation
from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryBookingPort,
    RecoveryDisposalRequest,
    RecoveryExternalBookingRequest,
)
from request_engine.modules.booking.contracts.recovery import (
    RecoveryTargetUnavailable as ExternalTargetUnavailable,
)
from request_engine.modules.live_capacity.contracts.recovery import RecoveryCapacitySource
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryTargetUnavailable,
)
from request_engine.modules.operational_recovery.application.workflow_assessment import (
    reconcile_recovery_incident,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ReplaceResourceRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.models import AffectedReservation
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionStatus,
    RecoveryExternalTarget,
    RecoveryIncident,
)

_EXTERNAL_COMMIT_FAILURE = "EXTERNAL_COMMIT_FAILED"


async def execute_external_replacement(
    command: ReplaceResourceRecoveryActionCommand,
    *,
    action: RecoveryAction,
    incident: RecoveryIncident,
    affected: AffectedReservation,
    workflow_repository: RecoveryWorkflowRepository,
    booking: RecoveryBookingPort,
    capacity: RecoveryCapacitySource,
) -> RecoveryAction:
    target = command.external_target
    if target is None:  # pragma: no cover - dispatch guarantees a target
        raise ValueError("external replacement requires an external target")
    external_reservation = await _commit_external(
        command, target, action, affected, booking, workflow_repository
    )
    disposed = await booking.cancel_for_recovery(
        RecoveryDisposalRequest(
            organization_id=command.organization_id,
            principal_id=command.principal_id,
            reservation_id=affected.reservation_id,
            expected_revision=affected.expected_revision,
            action_id=action.id,
            reason="replaced through cross-organization recovery",
        )
    )
    assessment, refreshed = await reconcile_recovery_incident(
        organization_id=command.organization_id,
        service_queue_id=incident.service_queue_id,
        repository=workflow_repository,
        capacity=capacity,
        current_proposal_id=incident.current_proposal_id,
    )
    return await workflow_repository.transition_action(
        organization_id=command.organization_id,
        action_id=action.id,
        expected_status=action.status,
        status=RecoveryActionStatus.SUCCEEDED,
        owner_steps={
            "external_commit": {
                "organization_id": str(target.organization_id),
                "reservation_id": str(external_reservation.id),
                "revision": external_reservation.revision,
                "subject_party_id": str(target.subject_party_id),
            },
            "source_disposal": {"reservation_id": str(disposed.id), "revision": disposed.revision},
            "reassessment": {
                "source_revision": assessment.checkpoint.recovery_source_revision,
                "incident_status": None if refreshed is None else refreshed.status.value,
            },
        },
    )


async def _commit_external(
    command: ReplaceResourceRecoveryActionCommand,
    target: RecoveryExternalTarget,
    action: RecoveryAction,
    affected: AffectedReservation,
    booking: RecoveryBookingPort,
    workflow_repository: RecoveryWorkflowRepository,
) -> Reservation:
    try:
        return await booking.book_discovered_option(
            RecoveryExternalBookingRequest(
                organization_id=target.organization_id,
                source_organization_id=command.organization_id,
                reservation_id=affected.reservation_id,
                action_id=action.id,
                option_id=target.option_id,
                subject_party_id=target.subject_party_id,
            )
        )
    except (ExternalTargetUnavailable, RecoveryBookingConflict) as exc:
        await workflow_repository.transition_action(
            organization_id=command.organization_id,
            action_id=action.id,
            expected_status=action.status,
            status=RecoveryActionStatus.REJECTED,
            failure_code=_EXTERNAL_COMMIT_FAILURE,
        )
        raise RecoveryTargetUnavailable(affected.reservation_id, str(exc)) from exc
