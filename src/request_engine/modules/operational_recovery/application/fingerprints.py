import hashlib
import json

from request_engine.modules.booking.contracts.appointments import ResourceChoice
from request_engine.modules.operational_recovery.application.commands import (
    CreateRecoveryProposalCommand,
    ExecuteRecoveryCommand,
)
from request_engine.modules.operational_recovery.contracts.models import (
    AffectedReservation,
    RecoverySourceCheckpoint,
    RecoveryTarget,
)


def proposal_command_fingerprint(command: CreateRecoveryProposalCommand) -> str:
    return _hash(
        {
            "service_queue_id": str(command.service_queue_id),
            "search_days": command.search_days,
        }
    )


def proposal_fingerprint(
    *,
    source_fingerprint: str,
    source_checkpoint: RecoverySourceCheckpoint,
    service_queue_id: object,
    resource_id: object,
    location_id: object,
    executable_capacity_seconds: int,
    committed_capacity_seconds: int,
    shortfall_seconds: int,
    affected: tuple[AffectedReservation, ...],
) -> str:
    return _hash(
        {
            "source_fingerprint": source_fingerprint,
            "source_checkpoint": checkpoint_payload(source_checkpoint),
            "service_queue_id": str(service_queue_id),
            "resource_id": str(resource_id),
            "location_id": str(location_id),
            "executable_capacity_seconds": executable_capacity_seconds,
            "committed_capacity_seconds": committed_capacity_seconds,
            "shortfall_seconds": shortfall_seconds,
            "affected": [affected_payload(item) for item in affected],
        }
    )


def execution_fingerprint(command: ExecuteRecoveryCommand, target: RecoveryTarget) -> str:
    return _hash(
        {
            "organization_id": str(command.organization_id),
            "principal_id": str(command.principal_id),
            "proposal_id": str(command.proposal_id),
            "reservation_id": str(command.reservation_id),
            "expected_source_fingerprint": command.expected_source_fingerprint,
            "expected_proposal_fingerprint": command.expected_proposal_fingerprint,
            "idempotency_key": command.idempotency_key,
            "allow_subject_override": command.allow_subject_override,
            "notify": command.notify,
            "target": target_payload(target),
        }
    )


def checkpoint_payload(checkpoint: RecoverySourceCheckpoint) -> dict[str, object]:
    return {
        "projection_policy_revision": checkpoint.projection_policy_revision,
        "resource_availability_revision": checkpoint.resource_availability_revision,
        "location_operational_revision": checkpoint.location_operational_revision,
        "recovery_source_revision": checkpoint.recovery_source_revision,
        "commitments": [
            {
                "reservation_id": str(item.reservation_id),
                "revision": item.revision,
                "starts_at": item.starts_at.isoformat(),
                "ends_at": item.ends_at.isoformat(),
            }
            for item in checkpoint.commitments
        ],
    }


def affected_payload(item: AffectedReservation) -> dict[str, object]:
    return {
        "reservation_id": str(item.reservation_id),
        "offering_version_id": str(item.offering_version_id),
        "subject_party_id": str(item.subject_party_id),
        "expected_revision": item.expected_revision,
        "original_start_at": item.original_start_at.isoformat(),
        "original_end_at": item.original_end_at.isoformat(),
        "target": target_payload(item.target) if item.target is not None else None,
        "replacement_target": (
            target_payload(item.replacement_target) if item.replacement_target is not None else None
        ),
    }


def target_payload(target: RecoveryTarget) -> dict[str, object]:
    return {
        "start_at": target.start_at.isoformat(),
        "end_at": target.end_at.isoformat(),
        "location_id": str(target.location_id),
        "resources": [resource_payload(item) for item in target.resources],
        "planned_duration_minutes": target.planned_duration_minutes,
        "amount": str(target.amount),
        "currency": target.currency,
        "location_operational_revision": target.location_operational_revision,
        "configuration_fingerprint": target.configuration_fingerprint,
    }


def resource_payload(choice: ResourceChoice) -> dict[str, object]:
    assignment = choice.resource_location_assignment_id
    return {
        "requirement_id": str(choice.requirement_id),
        "resource_id": str(choice.resource_id),
        "resource_location_assignment_id": str(assignment) if assignment else None,
        "assignment_revision": choice.assignment_revision,
        "availability_revision": choice.availability_revision,
    }


def _hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
