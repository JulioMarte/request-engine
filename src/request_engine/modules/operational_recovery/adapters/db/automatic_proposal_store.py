import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.affected_codec import (
    affected_to_json,
)
from request_engine.modules.operational_recovery.adapters.db.checkpoint_codec import (
    checkpoint_to_json,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal


async def find_automatic_proposal_id(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    source_revision: int,
) -> UUID | None:
    return (
        await session.execute(
            text(
                """
                SELECT id
                FROM request_engine.operational_recovery_proposals
                WHERE organization_id = :organization_id
                  AND service_queue_id = :service_queue_id
                  AND creation_kind = 'automatic'
                  AND source_revision = :source_revision
                """
            ),
            {
                "organization_id": organization_id,
                "service_queue_id": service_queue_id,
                "source_revision": source_revision,
            },
        )
    ).scalar_one_or_none()


async def insert_automatic_proposal(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_revision: int,
    proposal: RescheduleProposal,
) -> UUID:
    snapshot = {
        "source_snapshot": proposal.source_snapshot,
        "source_checkpoint": checkpoint_to_json(proposal.source_checkpoint),
        "affected": [affected_to_json(item) for item in proposal.affected],
    }
    params = {
        "id": proposal.id,
        "organization_id": organization_id,
        "service_queue_id": proposal.service_queue_id,
        "resource_id": proposal.resource_id,
        "location_id": proposal.location_id,
        "idempotency_key": f"automatic:{proposal.service_queue_id}:{source_revision}",
        "command_fingerprint": proposal.proposal_fingerprint,
        "observed_at": proposal.observed_at,
        "horizon_end": proposal.horizon_end,
        "source_fingerprint": proposal.source_fingerprint,
        "proposal_fingerprint": proposal.proposal_fingerprint,
        "executable_capacity_seconds": proposal.executable_capacity_seconds,
        "committed_capacity_seconds": proposal.committed_capacity_seconds,
        "shortfall_seconds": proposal.shortfall_seconds,
        "snapshot": json.dumps(snapshot, separators=(",", ":")),
        "source_revision": source_revision,
    }
    inserted = (
        await session.execute(
            text(
                """
                INSERT INTO request_engine.operational_recovery_proposals (
                    id, organization_id, service_queue_id, resource_id, location_id,
                    created_by_principal_id, idempotency_key, command_fingerprint,
                    observed_at, horizon_end, source_fingerprint, proposal_fingerprint,
                    executable_capacity_seconds, committed_capacity_seconds,
                    shortfall_seconds, snapshot, creation_kind, source_revision
                ) VALUES (
                    :id, :organization_id, :service_queue_id, :resource_id, :location_id,
                    NULL, :idempotency_key, :command_fingerprint,
                    :observed_at, :horizon_end, :source_fingerprint, :proposal_fingerprint,
                    :executable_capacity_seconds, :committed_capacity_seconds,
                    :shortfall_seconds, CAST(:snapshot AS jsonb), 'automatic', :source_revision
                )
                ON CONFLICT (organization_id, service_queue_id, source_revision)
                  WHERE creation_kind = 'automatic'
                DO NOTHING
                RETURNING id
                """
            ),
            params,
        )
    ).scalar_one_or_none()
    if inserted is not None:
        return inserted

    existing = await find_automatic_proposal_id(
        session,
        organization_id=organization_id,
        service_queue_id=proposal.service_queue_id,
        source_revision=source_revision,
    )
    if existing is None:
        raise RuntimeError("automatic recovery proposal conflict did not resolve a winner")
    return existing
