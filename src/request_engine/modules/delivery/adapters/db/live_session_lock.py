from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.adapters.db.live_common import (
    lock_queue,
    lock_queue_entry,
    lock_resource,
    require_session_probe,
)
from request_engine.modules.delivery.application.errors import ResourceExecutionUnavailable


async def lock_session_context(
    session: AsyncSession, organization_id: UUID, session_id: UUID
) -> tuple[RowMapping, RowMapping]:
    probe = await require_session_probe(session, organization_id, session_id)
    await lock_queue(session, organization_id, cast(UUID, probe["service_queue_id"]))
    entry = await lock_queue_entry(session, organization_id, cast(UUID, probe["queue_entry_id"]))
    await lock_resource(session, organization_id, cast(UUID, probe["resource_id"]))
    result = await session.execute(
        text(
            "SELECT id, queue_entry_id, resource_id, location_id, "
            "actual_workload_classification_id, status, started_at, completed_at, revision "
            "FROM request_engine.service_sessions "
            "WHERE organization_id=:organization_id AND id=:session_id FOR UPDATE"
        ),
        {"organization_id": organization_id, "session_id": session_id},
    )
    return entry, result.mappings().one()


async def require_execution_assignment(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    at: datetime,
) -> None:
    result = await session.execute(
        text(
            "SELECT 1 FROM request_engine.resource_location_assignments "
            "WHERE organization_id=:organization_id AND resource_id=:resource_id "
            "AND location_id=:location_id AND status='active' AND effective_during @> :at "
            "LIMIT 1"
        ),
        {
            "organization_id": organization_id,
            "resource_id": resource_id,
            "location_id": location_id,
            "at": at,
        },
    )
    if result.first() is None:
        raise ResourceExecutionUnavailable(resource_id, "no_active_location_assignment")
