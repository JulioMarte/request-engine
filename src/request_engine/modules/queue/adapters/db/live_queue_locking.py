from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import QueueInactive, QueueNotFound


async def lock_active_queue(
    session: AsyncSession, organization_id: UUID, queue_id: UUID
) -> RowMapping:
    row = (
        (
            await session.execute(
                text(
                    "SELECT id,location_id,offering_id,active "
                    "FROM request_engine.service_queues "
                    "WHERE organization_id=:organization_id AND id=:queue_id FOR UPDATE"
                ),
                {"organization_id": organization_id, "queue_id": queue_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise QueueNotFound(queue_id)
    if row["active"] is not True:
        raise QueueInactive(queue_id)
    return row


async def probe_queue_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    "SELECT service_queue_id FROM request_engine.queue_entries "
                    "WHERE organization_id=:organization_id AND id=:entry_id"
                ),
                {"organization_id": organization_id, "entry_id": entry_id},
            )
        )
        .mappings()
        .first()
    )


async def lock_queue_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    "SELECT id,service_queue_id,subject_party_id,reservation_id,offering_id,status,"
                    "arrived_at,admitted_at,called_at,expected_workload_classification_id,revision "
                    "FROM request_engine.queue_entries "
                    "WHERE organization_id=:organization_id AND id=:entry_id FOR UPDATE"
                ),
                {"organization_id": organization_id, "entry_id": entry_id},
            )
        )
        .mappings()
        .one()
    )
