from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def release_hold_by_id(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_entry_id: UUID,
    hold_id: UUID,
    principal_id: UUID,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.queue_recall_holds
                    SET released_at = clock_timestamp(),
                        released_by_principal_id = :principal_id,
                        release_reason = 'operator_release'
                    WHERE organization_id = :organization_id
                      AND queue_entry_id = :queue_entry_id
                      AND id = :hold_id
                      AND released_at IS NULL
                    RETURNING id, service_queue_id, queue_entry_id, hold_kind,
                              release_at, reason, created_at, released_at
                    """
                ),
                {
                    "organization_id": organization_id,
                    "queue_entry_id": queue_entry_id,
                    "hold_id": hold_id,
                    "principal_id": principal_id,
                },
            )
        )
        .mappings()
        .first()
    )
