from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.adapters.db.live_queue_locking import lock_queue_entry
from request_engine.modules.queue.application.errors import QueueEntryNotFound
from request_engine.modules.queue.application.same_day_selection_errors import (
    QueueEntryNotSelectable,
    QueueEntryRecallHeld,
)


async def lock_waiting_entry_in_queue(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
    queue_entry_id: UUID,
    *,
    require_callable: bool,
) -> RowMapping:
    try:
        row = await lock_queue_entry(session, organization_id, queue_entry_id)
    except Exception as exc:
        raise QueueEntryNotFound(queue_id, queue_entry_id) from exc
    if cast(UUID, row["service_queue_id"]) != queue_id:
        raise QueueEntryNotFound(queue_id, queue_entry_id)
    status = cast(str, row["status"])
    if status != "waiting":
        raise QueueEntryNotSelectable(queue_entry_id, status)
    if require_callable and await has_active_recall_hold(session, organization_id, queue_entry_id):
        raise QueueEntryRecallHeld(queue_entry_id)
    return row


async def has_active_recall_hold(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
) -> bool:
    row = (
        await session.execute(
            text(
                """
                SELECT 1
                FROM request_engine.queue_recall_holds
                WHERE organization_id = :organization_id
                  AND queue_entry_id = :queue_entry_id
                  AND released_at IS NULL
                  AND (
                      hold_kind = 'until_customer_initiates'
                      OR release_at > clock_timestamp()
                  )
                LIMIT 1
                """
            ),
            {"organization_id": organization_id, "queue_entry_id": queue_entry_id},
        )
    ).first()
    return row is not None


async def lock_eligible_fifo_entries(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
    *,
    limit: int,
) -> list[UUID]:
    rows = (
        await session.execute(
            text(
                """
                SELECT qe.id
                FROM request_engine.queue_entries qe
                WHERE qe.organization_id = :organization_id
                  AND qe.service_queue_id = :queue_id
                  AND qe.status = 'waiting'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM request_engine.queue_recall_holds h
                      WHERE h.organization_id = qe.organization_id
                        AND h.queue_entry_id = qe.id
                        AND h.released_at IS NULL
                        AND (
                            h.hold_kind = 'until_customer_initiates'
                            OR h.release_at > clock_timestamp()
                        )
                  )
                ORDER BY qe.admitted_at, qe.id
                LIMIT :limit
                FOR UPDATE OF qe
                """
            ),
            {"organization_id": organization_id, "queue_id": queue_id, "limit": limit},
        )
    ).all()
    return [cast(UUID, row[0]) for row in rows]
