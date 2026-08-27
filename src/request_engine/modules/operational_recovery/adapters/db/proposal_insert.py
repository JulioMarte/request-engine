import json
from uuid import UUID

from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal

INSERT_PROPOSAL = """
    INSERT INTO request_engine.operational_recovery_proposals (
        id, organization_id, service_queue_id, resource_id, location_id,
        created_by_principal_id, idempotency_key, command_fingerprint,
        observed_at, horizon_end, source_fingerprint, proposal_fingerprint,
        executable_capacity_seconds, committed_capacity_seconds, shortfall_seconds,
        snapshot
    ) VALUES (
        :id, :organization_id, :service_queue_id, :resource_id, :location_id,
        :principal_id, :idempotency_key, :command_fingerprint,
        :observed_at, :horizon_end, :source_fingerprint, :proposal_fingerprint,
        :executable_capacity_seconds, :committed_capacity_seconds, :shortfall_seconds,
        CAST(:snapshot AS jsonb)
    ) RETURNING created_at
"""


def proposal_insert_params(
    proposal: RescheduleProposal,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    command_fingerprint: str,
    snapshot: dict[str, object],
) -> dict[str, object]:
    return {
        "id": proposal.id,
        "organization_id": organization_id,
        "service_queue_id": proposal.service_queue_id,
        "resource_id": proposal.resource_id,
        "location_id": proposal.location_id,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
        "command_fingerprint": command_fingerprint,
        "observed_at": proposal.observed_at,
        "horizon_end": proposal.horizon_end,
        "source_fingerprint": proposal.source_fingerprint,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "executable_capacity_seconds": proposal.executable_capacity_seconds,
        "committed_capacity_seconds": proposal.committed_capacity_seconds,
        "shortfall_seconds": proposal.shortfall_seconds,
        "snapshot": json.dumps(snapshot, separators=(",", ":")),
    }
