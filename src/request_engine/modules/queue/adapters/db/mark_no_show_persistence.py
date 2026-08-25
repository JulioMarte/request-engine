from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import QueueEntryNotCancellable


async def require_no_service_session(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.service_sessions "
                "WHERE organization_id=:organization_id AND queue_entry_id=:entry_id"
            ),
            {"organization_id": organization_id, "entry_id": queue_entry_id},
        )
    ).first()
    if row is not None:
        raise QueueEntryNotCancellable(queue_entry_id, "service_session_exists")


async def persist_no_show(
    session: AsyncSession,
    organization_id: UUID,
    queue_entry_id: UUID,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    "UPDATE request_engine.queue_entries "
                    "SET status='no_show',revision=revision+1,"
                    "updated_at=clock_timestamp() "
                    "WHERE organization_id=:organization_id AND id=:entry_id "
                    "RETURNING id,service_queue_id,subject_party_id,reservation_id,"
                    "offering_id,status,arrived_at,admitted_at,called_at,"
                    "expected_workload_classification_id,revision"
                ),
                {"organization_id": organization_id, "entry_id": queue_entry_id},
            )
        )
        .mappings()
        .one()
    )
