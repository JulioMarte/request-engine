from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.operational_recovery.adapters.db.proposal_codec import (
    proposal_from_row,
)
from request_engine.modules.operational_recovery.application.errors import (
    RecoveryIdempotencyConflict,
)
from request_engine.modules.operational_recovery.contracts.models import RescheduleProposal
from request_engine.platform.db.session import SessionFactory, tenant_transaction

_SELECT = """
    SELECT * FROM request_engine.operational_recovery_proposals
    WHERE organization_id = :organization_id AND id = :proposal_id
"""
_REPLAY = """
    SELECT * FROM request_engine.operational_recovery_proposals
    WHERE organization_id = :organization_id
      AND created_by_principal_id = :principal_id
      AND idempotency_key = :idempotency_key
"""


async def require_proposal(
    session: AsyncSession,
    organization_id: UUID,
    proposal_id: UUID,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(_SELECT),
                {"organization_id": organization_id, "proposal_id": proposal_id},
            )
        )
        .mappings()
        .one()
    )


async def find_proposal_replay(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    command_fingerprint: str,
) -> RescheduleProposal | None:
    params = {
        "organization_id": organization_id,
        "principal_id": principal_id,
        "idempotency_key": idempotency_key,
    }
    async with tenant_transaction(factory, organization_id) as session:
        row = (await session.execute(text(_REPLAY), params)).mappings().one_or_none()
    if row is None:
        return None
    if cast(str, row["command_fingerprint"]) != command_fingerprint:
        raise RecoveryIdempotencyConflict()
    return proposal_from_row(row)


async def get_proposal(
    factory: SessionFactory,
    *,
    organization_id: UUID,
    proposal_id: UUID,
) -> RescheduleProposal | None:
    async with tenant_transaction(factory, organization_id) as session:
        row = (
            (
                await session.execute(
                    text(_SELECT),
                    {"organization_id": organization_id, "proposal_id": proposal_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    return proposal_from_row(row) if row is not None else None
