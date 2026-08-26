from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.application.errors import (
    LiveServiceRevisionConflict,
    QueueEntryNotCallable,
    ResourceExecutionUnavailable,
    ServiceSessionNotFound,
    WorkloadClassificationUnavailable,
)


async def db_now(session: AsyncSession) -> datetime:
    value = await session.execute(text("SELECT clock_timestamp()"))
    return cast(datetime, value.scalar_one())


async def probe_queue_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping:
    result = await session.execute(
        text(
            "SELECT id, service_queue_id FROM request_engine.queue_entries "
            "WHERE organization_id=:organization_id AND id=:entry_id"
        ),
        {"organization_id": organization_id, "entry_id": entry_id},
    )
    row = result.mappings().first()
    if row is None:
        raise QueueEntryNotCallable(entry_id, "missing")
    return row


async def lock_queue(session: AsyncSession, organization_id: UUID, queue_id: UUID) -> None:
    result = await session.execute(
        text(
            "SELECT id FROM request_engine.service_queues "
            "WHERE organization_id=:organization_id AND id=:queue_id AND active FOR UPDATE"
        ),
        {"organization_id": organization_id, "queue_id": queue_id},
    )
    if result.first() is None:
        raise QueueEntryNotCallable(queue_id, "queue_missing_or_inactive")


async def lock_queue_entry(
    session: AsyncSession, organization_id: UUID, entry_id: UUID
) -> RowMapping:
    result = await session.execute(
        text(
            "SELECT id, service_queue_id, subject_party_id, status, revision "
            "FROM request_engine.queue_entries "
            "WHERE organization_id=:organization_id AND id=:entry_id FOR UPDATE"
        ),
        {"organization_id": organization_id, "entry_id": entry_id},
    )
    row = result.mappings().first()
    if row is None:
        raise QueueEntryNotCallable(entry_id, "missing")
    return row


async def lock_resource(session: AsyncSession, organization_id: UUID, resource_id: UUID) -> None:
    result = await session.execute(
        text(
            "SELECT active FROM request_engine.resources "
            "WHERE organization_id=:organization_id AND id=:resource_id FOR UPDATE"
        ),
        {"organization_id": organization_id, "resource_id": resource_id},
    )
    row = result.first()
    if row is None or row[0] is not True:
        raise ResourceExecutionUnavailable(resource_id, "missing_or_inactive")


async def require_workload(
    session: AsyncSession, organization_id: UUID, workload_id: UUID | None
) -> None:
    if workload_id is None:
        return
    result = await session.execute(
        text(
            "SELECT 1 FROM request_engine.operational_workload_classifications "
            "WHERE organization_id=:organization_id AND id=:workload_id AND active"
        ),
        {"organization_id": organization_id, "workload_id": workload_id},
    )
    if result.first() is None:
        raise WorkloadClassificationUnavailable(workload_id)


def require_revision(row: RowMapping, aggregate_id: UUID, expected: int) -> None:
    actual = cast(int, row["revision"])
    if actual != expected:
        raise LiveServiceRevisionConflict(aggregate_id, expected, actual)


async def require_session_probe(
    session: AsyncSession, organization_id: UUID, session_id: UUID
) -> RowMapping:
    result = await session.execute(
        text(
            "SELECT s.queue_entry_id, s.resource_id, e.service_queue_id "
            "FROM request_engine.service_sessions s JOIN request_engine.queue_entries e "
            "ON e.organization_id=s.organization_id AND e.id=s.queue_entry_id "
            "WHERE s.organization_id=:organization_id AND s.id=:session_id"
        ),
        {"organization_id": organization_id, "session_id": session_id},
    )
    row = result.mappings().first()
    if row is None:
        raise ServiceSessionNotFound(session_id)
    return row
