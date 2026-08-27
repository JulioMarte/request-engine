from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

_BY_PROPOSAL = """
    SELECT * FROM request_engine.operational_recovery_executions
    WHERE organization_id = :organization_id
      AND proposal_id = :proposal_id AND reservation_id = :reservation_id
"""
_BY_KEY = """
    SELECT * FROM request_engine.operational_recovery_executions
    WHERE organization_id = :organization_id
      AND executed_by_principal_id = :principal_id
      AND idempotency_key = :idempotency_key
"""


async def find_execution_conflict(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    idempotency_key: str,
    proposal_id: UUID,
    reservation_id: UUID,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(_BY_PROPOSAL),
                {
                    "organization_id": organization_id,
                    "proposal_id": proposal_id,
                    "reservation_id": reservation_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is not None:
        return row
    row = (
        (
            await session.execute(
                text(_BY_KEY),
                {
                    "organization_id": organization_id,
                    "principal_id": principal_id,
                    "idempotency_key": idempotency_key,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise RuntimeError("recovery execution conflict could not be resolved")
    return row
