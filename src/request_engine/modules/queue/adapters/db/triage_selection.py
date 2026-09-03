from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def expire_queue_time_holds(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.queue_entry_recall_holds h
               SET released_at = clock_timestamp(), release_kind = 'expired'
             WHERE h.organization_id = :organization_id
               AND h.released_at IS NULL AND h.condition_kind = 'until_time'
               AND h.until_at <= clock_timestamp()
               AND EXISTS (
                   SELECT 1 FROM request_engine.queue_entries e
                    WHERE e.organization_id = h.organization_id
                      AND e.id = h.queue_entry_id
                      AND e.service_queue_id = :queue_id
               )
            """
        ),
        {"organization_id": organization_id, "queue_id": queue_id},
    )


async def lock_next_eligible_entry(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
) -> UUID | None:
    await expire_queue_time_holds(session, organization_id, queue_id)
    row = (
        await session.execute(
            text(
                """
                SELECT e.id
                  FROM request_engine.queue_entries e
                 WHERE e.organization_id = :organization_id
                   AND e.service_queue_id = :queue_id AND e.status = 'waiting'
                   AND NOT EXISTS (
                       SELECT 1 FROM request_engine.queue_entry_recall_holds h
                        WHERE h.organization_id = e.organization_id
                          AND h.queue_entry_id = e.id AND h.released_at IS NULL
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM request_engine.queue_entry_skips s
                        WHERE s.organization_id = e.organization_id
                          AND s.queue_entry_id = e.id AND s.consumed_at IS NULL
                   )
                 ORDER BY e.admitted_at, e.id
                 LIMIT 1
                 FOR UPDATE OF e
                """
            ),
            {"organization_id": organization_id, "queue_id": queue_id},
        )
    ).first()
    return None if row is None else cast(UUID, row[0])


async def consume_active_skips(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
    selected_entry_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            WITH consumed AS (
                UPDATE request_engine.queue_entry_skips s
                   SET consumed_at = clock_timestamp(),
                       consumed_by_entry_id = :selected_entry_id
                 WHERE s.organization_id = :organization_id
                   AND s.consumed_at IS NULL
                   AND EXISTS (
                       SELECT 1 FROM request_engine.queue_entries q
                        WHERE q.organization_id = s.organization_id
                          AND q.id = s.queue_entry_id
                          AND q.service_queue_id = :queue_id
                   )
                RETURNING queue_entry_id
            )
            UPDATE request_engine.queue_entries e
               SET revision = revision + 1
             WHERE e.organization_id = :organization_id AND e.status = 'waiting'
               AND e.id IN (SELECT queue_entry_id FROM consumed)
            """
        ),
        {
            "organization_id": organization_id,
            "queue_id": queue_id,
            "selected_entry_id": selected_entry_id,
        },
    )
