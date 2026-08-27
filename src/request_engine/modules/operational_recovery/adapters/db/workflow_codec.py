from datetime import datetime
from typing import Mapping, cast
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.workflow import (
    RecoveryAction,
    RecoveryActionKind,
    RecoveryActionStatus,
    RecoveryImpactKind,
    RecoveryIncident,
    RecoveryIncidentStatus,
)


def incident_from_row(row: Mapping[str, object]) -> RecoveryIncident:
    return RecoveryIncident(
        id=cast(UUID, row["id"]),
        organization_id=cast(UUID, row["organization_id"]),
        service_queue_id=cast(UUID, row["service_queue_id"]),
        resource_id=cast(UUID, row["resource_id"]),
        location_id=cast(UUID, row["location_id"]),
        status=RecoveryIncidentStatus(cast(str, row["status"])),
        impact_kind=RecoveryImpactKind(cast(str, row["impact_kind"])),
        escalation_level=cast(int, row["escalation_level"]),
        source_revision=cast(int, row["source_revision"]),
        source_fingerprint=cast(str, row["source_fingerprint"]),
        current_proposal_id=cast(UUID | None, row["current_proposal_id"]),
        opened_at=cast(datetime, row["opened_at"]),
        last_assessed_at=cast(datetime, row["last_assessed_at"]),
        resolved_at=cast(datetime | None, row["resolved_at"]),
        revision=cast(int, row["revision"]),
    )


def action_from_row(row: Mapping[str, object]) -> RecoveryAction:
    return RecoveryAction(
        id=cast(UUID, row["id"]),
        organization_id=cast(UUID, row["organization_id"]),
        incident_id=cast(UUID, row["incident_id"]),
        action_kind=RecoveryActionKind(cast(str, row["action_kind"])),
        status=RecoveryActionStatus(cast(str, row["status"])),
        principal_id=cast(UUID, row["principal_id"]),
        idempotency_key=cast(str, row["idempotency_key"]),
        command_fingerprint=cast(str, row["command_fingerprint"]),
        expected_source_revision=cast(int, row["expected_source_revision"]),
        payload=cast(dict[str, object], row["payload"]),
        owner_steps=cast(dict[str, object], row["owner_steps"]),
        failure_code=cast(str | None, row["failure_code"]),
        created_at=cast(datetime, row["created_at"]),
        started_at=cast(datetime | None, row["started_at"]),
        completed_at=cast(datetime | None, row["completed_at"]),
    )
