from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def has_active_recall_hold(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_id: UUID,
    observed_at: datetime,
) -> bool:
    row = (
        await session.execute(
            text(
                """
                SELECT 1
                FROM request_engine.queue_recall_holds
                WHERE organization_id = :organization_id
                  AND service_queue_id = :queue_id
                  AND released_at IS NULL
                  AND (
                      hold_kind = 'until_customer_initiates'
                      OR release_at > :observed_at
                  )
                LIMIT 1
                """
            ),
            {
                "organization_id": organization_id,
                "queue_id": queue_id,
                "observed_at": observed_at,
            },
        )
    ).first()
    return row is not None
