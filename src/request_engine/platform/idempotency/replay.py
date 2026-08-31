from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_completed_idempotency_result(
    session: AsyncSession,
    *,
    organization_id: UUID,
    principal_id: UUID,
    capability: str,
    idempotency_key: str,
) -> dict[str, object] | None:
    """Read a completed command result without reacquiring it with a new fingerprint."""

    result = (
        await session.execute(
            text(
                """
                SELECT result_data
                FROM request_engine.idempotency_records
                WHERE organization_id = :organization_id
                  AND principal_id = :principal_id
                  AND capability = :capability
                  AND idempotency_key = :idempotency_key
                  AND status = 'completed'
                """
            ),
            {
                "organization_id": organization_id,
                "principal_id": principal_id,
                "capability": capability,
                "idempotency_key": idempotency_key,
            },
        )
    ).scalar_one_or_none()
    if result is None:
        return None
    if not isinstance(result, dict):
        raise RuntimeError("completed idempotency record has no object result")
    return cast(dict[str, object], result)
