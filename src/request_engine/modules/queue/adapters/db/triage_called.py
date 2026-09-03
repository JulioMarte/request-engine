import json
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def mark_entry_called(
    session: AsyncSession,
    organization_id: UUID,
    entry_id: UUID,
) -> int:
    row = (
        await session.execute(
            text(
                """
                UPDATE request_engine.queue_entries
                   SET status = 'called',
                       called_at = clock_timestamp(),
                       revision = revision + 1
                 WHERE organization_id = :organization_id
                   AND id = :entry_id AND status = 'waiting'
                 RETURNING service_queue_id, subject_party_id, called_at, revision
                """
            ),
            {"organization_id": organization_id, "entry_id": entry_id},
        )
    ).one()
    await session.execute(
        text(
            """
            INSERT INTO request_engine.outbox_messages (
                organization_id, event_type, schema_version,
                aggregate_kind, aggregate_id, payload
            ) VALUES (
                :organization_id, 'queue.entry_called.v1', 1,
                'QueueEntry', :entry_id, CAST(:payload AS jsonb)
            )
            """
        ),
        {
            "organization_id": organization_id,
            "entry_id": entry_id,
            "payload": json.dumps(
                {
                    "queue_entry_id": str(entry_id),
                    "queue_id": str(row[0]),
                    "subject_party_id": str(row[1]),
                    "called_at": row[2].isoformat(),
                },
                separators=(",", ":"),
            ),
        },
    )
    return cast(int, row[3])
