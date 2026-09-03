from typing import Literal, cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TriageGate = Literal["hold", "skip"]


async def active_gate(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> TriageGate | None:
    row = (
        await session.execute(
            text(
                """
                SELECT 'hold' AS gate
                  FROM request_engine.queue_entry_recall_holds
                 WHERE organization_id = :organization_id
                   AND queue_entry_id = :entry_id AND released_at IS NULL
                UNION ALL
                SELECT 'skip' AS gate
                  FROM request_engine.queue_entry_skips
                 WHERE organization_id = :organization_id
                   AND queue_entry_id = :entry_id AND consumed_at IS NULL
                LIMIT 1
                """
            ),
            {"organization_id": organization_id, "entry_id": entry_id},
        )
    ).first()
    return None if row is None else cast(TriageGate, row[0])
