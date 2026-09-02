from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def bump_waiting_entry_revision(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
) -> int:
    row = (
        await session.execute(
            text(
                """
                UPDATE request_engine.queue_entries
                SET revision = revision + 1
                WHERE organization_id = :organization_id
                  AND id = :queue_entry_id
                  AND status = 'waiting'
                RETURNING revision
                """
            ),
            {"organization_id": organization_id, "queue_entry_id": queue_entry_id},
        )
    ).one()
    return cast(int, row[0])
