from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def read_completed_reservation_ids(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_id: UUID,
    reservation_ids: tuple[UUID, ...],
) -> frozenset[UUID]:
    if not reservation_ids:
        return frozenset()
    rows = (
        await session.execute(
            text(
                """
                SELECT DISTINCT reservation_id
                FROM request_engine.queue_entries
                WHERE organization_id = :organization_id
                  AND service_queue_id = :queue_id
                  AND status = 'completed'
                  AND reservation_id = ANY(CAST(:reservation_ids AS uuid[]))
                """
            ),
            {
                "organization_id": organization_id,
                "queue_id": queue_id,
                "reservation_ids": list(reservation_ids),
            },
        )
    ).scalars()
    return frozenset(cast(UUID, value) for value in rows)
