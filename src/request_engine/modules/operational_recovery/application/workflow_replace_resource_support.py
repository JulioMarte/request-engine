from collections.abc import Mapping

from request_engine.modules.operational_recovery.application.workflow_commands import (
    ReplaceResourceRecoveryActionCommand,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryIncident,
    RecoveryIncidentStale,
)
from request_engine.platform.idempotency.postgres import command_fingerprint


def replace_resource_payload(
    command: ReplaceResourceRecoveryActionCommand,
) -> dict[str, object]:
    return {
        "proposal_id": command.proposal_id,
        "reservation_id": command.reservation_id,
        "expected_source_fingerprint": command.expected_source_fingerprint,
        "expected_proposal_fingerprint": command.expected_proposal_fingerprint,
        "allow_subject_override": command.allow_subject_override,
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
