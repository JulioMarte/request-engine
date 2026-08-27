from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.operational_recovery.adapters.db.affected_codec import (
    affected_to_json,
)
from request_engine.modules.operational_recovery.adapters.db.checkpoint_codec import (
    checkpoint_to_json,
)
from request_engine.modules.operational_recovery.adapters.db.proposal_codec import (
    proposal_from_row,
    with_created_at,
)
from request_engine.modules.operational_recovery.adapters.db.proposal_insert import (
    INSERT_PROPOSAL,
    proposal_insert_params,
)
from request_engine.modules.operational_recovery.adapters.db.proposal_query_store import (
    require_proposal,
)
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryIdempotencyConflict,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.idempotency.errors import IdempotencyConflict
from request_engine.platform.idempotency.postgres import (
    acquire_idempotency,
    complete_idempotency,
)

_PROPOSE_CAPABILITY = "operational_recovery.propose"


async def create_proposal(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    command_fingerprint: str,
    proposal: RescheduleProposal,
) -> RescheduleProposal:
    snapshot: dict[str, object] = {
        "source_checkpoint": checkpoint_to_json(proposal.source_checkpoint),
        "affected": [affected_to_json(item) for item in proposal.affected],
    }
    async with tenant_transaction(factory, organization_id) as session:
        try:
            idempotency_id, replay = await acquire_idempotency(
                session,
                organization_id=organization_id,
                principal_id=principal_id,
                capability=_PROPOSE_CAPABILITY,
                idempotency_key=idempotency_key,
                fingerprint=command_fingerprint,
            )
        except IdempotencyConflict as exc:
            raise RecoveryIdempotencyConflict() from exc
        if replay is not None:
            proposal_id = UUID(cast(str, replay["proposal_id"]))
            row = await require_proposal(session, organization_id, proposal_id)
            return proposal_from_row(row)
        params = proposal_insert_params(
            proposal,
            organization_id=organization_id,
            principal_id=principal_id,
            idempotency_key=idempotency_key,
            command_fingerprint=command_fingerprint,
            snapshot=snapshot,
        )
        created_at = cast(
            datetime,
            (await session.execute(text(INSERT_PROPOSAL), params)).scalar_one(),
        )
        await complete_idempotency(
            session,
            idempotency_id,
            {"proposal_id": str(proposal.id)},
        )
    return with_created_at(proposal, created_at)
