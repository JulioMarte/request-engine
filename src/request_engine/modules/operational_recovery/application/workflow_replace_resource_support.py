from collections.abc import Mapping

from request_engine.modules.operational_recovery.application import (
    workflow_replace_resource_owner as replace_owner,
)
from request_engine.modules.operational_recovery.application.workflow_action_execution import (
    authorize_or_resume_action,
)
from request_engine.modules.operational_recovery.application.workflow_commands import (
    ReplaceResourceRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.application.workflow_ports import (
    RecoveryWorkflowRepository,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryIncident,
    RecoveryIncidentStale,
)
from request_engine.platform.idempotency.postgres import command_fingerprint


async def authorize_replace_resource(
    command: ReplaceResourceRecoveryActionCommand,
    *,
    workflow_repository: RecoveryWorkflowRepository,
    incident: RecoveryIncident,
    proposal: RescheduleProposal,
) -> tuple[RecoveryAction, bool]:
    """Authorize or resume the replace_resource action and fail closed when stale."""

    payload = replace_resource_payload(command)
    action, terminal, newly_authorized = await authorize_or_resume_action(
        repository=workflow_repository,
        incident=incident,
        organization_id=command.organization_id,
        principal_id=command.principal_id,
        action_kind=RecoveryActionKind.REPLACE_RESOURCE,
        idempotency_key=command.idempotency_key,
        command_fingerprint=replace_resource_fingerprint(command, payload),
        expected_source_revision=command.expected_source_revision,
        payload=payload,
    )
    if newly_authorized and not terminal:
        try:
            validate_fresh_replace_resource_authorization(
                command, incident=incident, proposal=proposal
            )
        except RecoveryIncidentStale:
            await replace_owner.reject_replace_resource_action(
                workflow_repository, command, action, "STALE_RECOVERY_INCIDENT"
            )
            raise
    return action, terminal


def replace_resource_payload(
    command: ReplaceResourceRecoveryActionCommand,
) -> dict[str, object]:
    return {
        "proposal_id": command.proposal_id,
        "reservation_id": command.reservation_id,
        "expected_source_fingerprint": command.expected_source_fingerprint,
        "expected_proposal_fingerprint": command.expected_proposal_fingerprint,
        "allow_subject_override": command.allow_subject_override,
        "external_target": (
            None
            if command.external_target is None
            else {
                "organization_id": str(command.external_target.organization_id),
                "subject_party_id": str(command.external_target.subject_party_id),
                "option_id": command.external_target.option_id,
            }
        ),
    }


def replace_resource_fingerprint(
    command: ReplaceResourceRecoveryActionCommand,
    payload: Mapping[str, object],
) -> str:
    return command_fingerprint(
        "operational_recovery.replace_resource.v1",
        {"expected_source_revision": command.expected_source_revision, **payload},
    )


def validate_fresh_replace_resource_authorization(
    command: ReplaceResourceRecoveryActionCommand,
    *,
    incident: RecoveryIncident,
    proposal: RescheduleProposal,
) -> None:
    valid = (
        proposal.service_queue_id == incident.service_queue_id
        and proposal.source_checkpoint.recovery_source_revision == command.expected_source_revision
        and proposal.source_fingerprint == command.expected_source_fingerprint
        and proposal.proposal_fingerprint == command.expected_proposal_fingerprint
        and (incident.current_proposal_id is None or incident.current_proposal_id == proposal.id)
    )
    if not valid:
        raise RecoveryIncidentStale(
            incident.id,
            command.expected_source_revision,
            incident.source_revision,
        )
