from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_active_recall_hold(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
    hold_id: UUID,
) -> RowMapping | None:
    return await _lock_recall_hold(
        session,
        organization_id=organization_id,
        queue_entry_id=queue_entry_id,
        hold_id=hold_id,
    )


async def lock_current_recall_hold(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
) -> RowMapping | None:
    return await _lock_recall_hold(
        session,
        organization_id=organization_id,
        queue_entry_id=queue_entry_id,
        hold_id=None,
    )


async def _lock_recall_hold(
    session: AsyncSession,
    *,
    organization_id: UUID,
    queue_entry_id: UUID,
    hold_id: UUID | None,
) -> RowMapping | None:
    row = (
        await session.execute(
            text(
                """
                SELECT id, service_queue_id, queue_entry_id, hold_kind,
                       release_at, reason, created_at, released_at
                FROM request_engine.queue_recall_holds
                WHERE organization_id = :organization_id
                  AND queue_entry_id = :queue_entry_id
                  AND (:hold_id IS NULL OR id = :hold_id)
                  AND released_at IS NULL
                  AND (
                      hold_kind = 'until_customer_initiates'
                      OR release_at > clock_timestamp()
                  )
                FOR UPDATE
                """
            ),
            {
                "organization_id": organization_id,
                "queue_entry_id": queue_entry_id,
                "hold_id": hold_id,
            },
        )
    ).mappings()
    return row.first()
