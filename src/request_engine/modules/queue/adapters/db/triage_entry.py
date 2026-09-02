from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import QueueEntryRevisionConflict
from request_engine.modules.queue.application.triage_errors import (
    QueueEntryNotWaiting,
    TriageQueueEntryNotFound,
)


async def queue_id_for_entry(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> UUID:
    row = (
        await session.execute(
            text(
                """
                SELECT service_queue_id
                  FROM request_engine.queue_entries
                 WHERE organization_id = :organization_id AND id = :entry_id
                """
            ),
            {"organization_id": organization_id, "entry_id": entry_id},
        )
    ).first()
    if row is None:
        raise TriageQueueEntryNotFound(entry_id)
    return cast(UUID, row[0])


async def lock_waiting_entry(
    session: AsyncSession,
    organization_id: UUID,
    queue_id: UUID,
    entry_id: UUID,
    expected_revision: int,
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, service_queue_id, status, revision
                      FROM request_engine.queue_entries
                     WHERE organization_id = :organization_id
                       AND service_queue_id = :queue_id AND id = :entry_id
                     FOR UPDATE
                    """
                ),
                {
                    "organization_id": organization_id,
                    "queue_id": queue_id,
                    "entry_id": entry_id,
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise TriageQueueEntryNotFound(entry_id)
    actual = cast(int, row["revision"])
    if actual != expected_revision:
        raise QueueEntryRevisionConflict(entry_id, expected_revision, actual)
    status = cast(str, row["status"])
    if status != "waiting":
        raise QueueEntryNotWaiting(entry_id, status)
    return row


async def bump_waiting_revision(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> int:
    row = (
        await session.execute(
            text(
                """
                UPDATE request_engine.queue_entries
                   SET revision = revision + 1
                 WHERE organization_id = :organization_id
                   AND id = :entry_id AND status = 'waiting'
                 RETURNING revision
                """
            ),
            {"organization_id": organization_id, "entry_id": entry_id},
        )
    ).one()
    return cast(int, row[0])


async def expire_time_hold(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> None:
    await session.execute(
        text(
            """
            UPDATE request_engine.queue_entry_recall_holds
               SET released_at = clock_timestamp(), release_kind = 'expired'
             WHERE organization_id = :organization_id
               AND queue_entry_id = :entry_id AND released_at IS NULL
               AND condition_kind = 'until_time' AND until_at <= clock_timestamp()
            """
        ),
        {"organization_id": organization_id, "entry_id": entry_id},
    )
