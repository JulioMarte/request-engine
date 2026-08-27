import json
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.proposal_codec import affected_to_json, checkpoint_to_json, proposal_from_row, with_created_at
from request_engine.modules.operational_recovery.application.errors import RecoveryIdempotencyConflict
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.idempotency.postgres import acquire_idempotency, complete_idempotency

_PROPOSE_CAPABILITY = "operational_recovery.propose"
_SELECT = "SELECT * FROM request_engine.operational_recovery_proposals WHERE organization_id = :organization_id AND id = :proposal_id"
_REPLAY = "SELECT * FROM request_engine.operational_recovery_proposals WHERE organization_id = :organization_id AND created_by_principal_id = :principal_id AND idempotency_key = :idempotency_key"
_INSERT = """INSERT INTO request_engine.operational_recovery_proposals (id, organization_id, service_queue_id, resource_id, location_id, created_by_principal_id, idempotency_key, command_fingerprint, observed_at, horizon_end, source_fingerprint, proposal_fingerprint, executable_capacity_seconds, committed_capacity_seconds, shortfall_seconds, snapshot) VALUES (:id, :organization_id, :service_queue_id, :resource_id, :location_id, :principal_id, :idempotency_key, :command_fingerprint, :observed_at, :horizon_end, :source_fingerprint, :proposal_fingerprint, :executable_capacity_seconds, :committed_capacity_seconds, :shortfall_seconds, CAST(:snapshot AS jsonb)) RETURNING created_at"""


async def find_proposal_replay(factory: SessionFactory, *, organization_id: UUID, principal_id: UUID, idempotency_key: str, command_fingerprint: str) -> RescheduleProposal | None:
    async with tenant_transaction(factory, organization_id) as session:
        row = ((await session.execute(text(_REPLAY), {"organization_id": organization_id, "principal_id": principal_id, "idempotency_key": idempotency_key})).mappings().one_or_none())
    if row is None:
        return None
    if cast(str, row["command_fingerprint"]) != command_fingerprint:
        raise RecoveryIdempotencyConflict()
    return proposal_from_row(row)


async def get_proposal(factory: SessionFactory, *, organization_id: UUID, proposal_id: UUID) -> RescheduleProposal | None:
    async with tenant_transaction(factory, organization_id) as session:
        row = ((await session.execute(text(_SELECT), {"organization_id": organization_id, "proposal_id": proposal_id})).mappings().one_or_none())
    return proposal_from_row(row) if row is not None else None


async def create_proposal(factory: SessionFactory, *, organization_id: UUID, principal_id: UUID, idempotency_key: str, command_fingerprint: str, proposal: RescheduleProposal) -> RescheduleProposal:
    snapshot = {"source_checkpoint": checkpoint_to_json(proposal.source_checkpoint), "affected": [affected_to_json(item) for item in proposal.affected]}
    async with tenant_transaction(factory, organization_id) as session:
        try:
            idempotency_id, replay = await acquire_idempotency(session, organization_id=organization_id, principal_id=principal_id, capability=_PROPOSE_CAPABILITY, idempotency_key=idempotency_key, fingerprint=command_fingerprint)
        except IdempotencyConflict as exc:
            raise RecoveryIdempotencyConflict() from exc
        if replay is not None:
            proposal_id = UUID(cast(str, replay["proposal_id"]))
            row = ((await session.execute(text(_SELECT), {"organization_id": organization_id, "proposal_id": proposal_id})).mappings().one())
            return proposal_from_row(row)
        params = {
            "id": proposal.id, "organization_id": organization_id, "service_queue_id": proposal.service_queue_id, "resource_id": proposal.resource_id, "location_id": proposal.location_id,
            "principal_id": principal_id, "idempotency_key": idempotency_key, "command_fingerprint": command_fingerprint, "observed_at": proposal.observed_at, "horizon_end": proposal.horizon_end,
            "source_fingerprint": proposal.source_fingerprint, "proposal_fingerprint": proposal.proposal_fingerprint, "executable_capacity_seconds": proposal.executable_capacity_seconds,
            "committed_capacity_seconds": proposal.committed_capacity_seconds, "shortfall_seconds": proposal.shortfall_seconds, "snapshot": json.dumps(snapshot, separators=(",", ":")),
        }
        created_at = cast(datetime, (await session.execute(text(_INSERT), params)).scalar_one())
        await complete_idempotency(session, idempotency_id, {"proposal_id": str(proposal.id)})
    return with_created_at(proposal, created_at)
