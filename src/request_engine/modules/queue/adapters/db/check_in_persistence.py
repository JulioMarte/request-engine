from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.queue.application.errors import AlreadyInQueue
from request_engine.modules.queue.application.live_commands import CheckInCommand


async def ensure_subject_not_active(
    session: AsyncSession,
    command: CheckInCommand,
) -> None:
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM request_engine.queue_entries "
                "WHERE organization_id=:organization_id AND service_queue_id=:queue_id "
                "AND subject_party_id=:subject_party_id "
                "AND status IN ('waiting','called','serving')"
            ),
            {
                "organization_id": command.organization_id,
                "queue_id": command.queue_id,
                "subject_party_id": command.subject_party_id,
            },
        )
    ).first()
    if row is not None:
        raise AlreadyInQueue(command.queue_id, command.subject_party_id)


async def insert_queue_entry(
    session: AsyncSession,
    command: CheckInCommand,
    offering_id: UUID | None,
) -> RowMapping:
    raw_now = (await session.execute(text("SELECT clock_timestamp()"))).scalar_one()
    if not isinstance(raw_now, datetime):
        raise RuntimeError("PostgreSQL clock_timestamp() did not return datetime")
    return (
        await session.execute(
            text(
                "INSERT INTO request_engine.queue_entries "
                "(organization_id,service_queue_id,subject_party_id,reservation_id,"
                "offering_id,arrived_at,admitted_at,"
                "expected_workload_classification_id) VALUES "
                "(:organization_id,:queue_id,:subject_party_id,:reservation_id,"
                ":offering_id,:now,:now,:workload_id) RETURNING "
                "id,service_queue_id,subject_party_id,reservation_id,offering_id,status,"
                "arrived_at,admitted_at,called_at,expected_workload_classification_id,revision"
            ),
            {
                "organization_id": command.organization_id,
                "queue_id": command.queue_id,
                "subject_party_id": command.subject_party_id,
                "reservation_id": command.reservation_id,
                "offering_id": offering_id,
                "now": raw_now,
                "workload_id": command.expected_workload_classification_id,
            },
        )
    ).mappings().one()
