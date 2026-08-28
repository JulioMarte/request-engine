from collections.abc import Mapping
from uuid import UUID

from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionConflict,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryIncident,
    RecoveryIncidentStale,
    RecoveryIncidentStatus,
)


async def authorize_or_resume_action(
    *,
    repository: RecoveryWorkflowRepository,
    incident: RecoveryIncident,
    organization_id: UUID,
    principal_id: UUID,
    action_kind: RecoveryActionKind,
    idempotency_key: str,
    command_fingerprint: str,
    expected_source_revision: int,
    payload: Mapping[str, object],
) -> tuple[RecoveryAction, bool]:
    action, created = await repository.prepare_action(
        organization_id=organization_id,
        incident_id=incident.id,
        principal_id=principal_id,
        action_kind=action_kind,
        idempotency_key=idempotency_key,
        command_fingerprint=command_fingerprint,
        expected_source_revision=expected_source_revision,
        payload=payload,
    )
    if not created and action.status in {
        RecoveryActionStatus.SUCCEEDED,
        RecoveryActionStatus.REJECTED,
    }:
        return action, True
    if action.status in {
        RecoveryActionStatus.RUNNING,
        RecoveryActionStatus.PARTIALLY_APPLIED,
    }:
        return action, False
    if action.status is not RecoveryActionStatus.PREPARED:
        raise RecoveryActionConflict(f"cannot resume recovery action in {action.status.value}")
    if (
        incident.status is RecoveryIncidentStatus.RESOLVED
        or incident.source_revision != expected_source_revision
    ):
        await repository.transition_action(
            organization_id=organization_id,
            action_id=action.id,
            expected_status=RecoveryActionStatus.PREPARED,
            status=RecoveryActionStatus.REJECTED,
            failure_code="STALE_RECOVERY_INCIDENT",
        )
        raise RecoveryIncidentStale(
            incident.id,
            expected_source_revision,
            incident.source_revision,
        )
    action = await repository.transition_action(
        organization_id=organization_id,
        action_id=action.id,
        expected_status=RecoveryActionStatus.PREPARED,
        status=RecoveryActionStatus.RUNNING,
    )
    return action, False
