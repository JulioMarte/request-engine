from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.adapters.db.live_serialization import session_from_row
from request_engine.modules.delivery.application.service_session_commands import StartServiceCommand
from request_engine.modules.delivery.contracts.service_session import ServiceSession


async def insert_service_session(
    session: AsyncSession,
    command: StartServiceCommand,
    started_at: datetime,
) -> ServiceSession:
    row = await session.execute(
        text(
            "INSERT INTO request_engine.service_sessions "
            "(organization_id,queue_entry_id,resource_id,location_id,"
            "actual_workload_classification_id,started_at) VALUES "
            "(:organization_id,:entry_id,:resource_id,:location_id,"
            ":workload_id,:started_at) RETURNING id,queue_entry_id,resource_id,"
            "location_id,actual_workload_classification_id,status,"
            "started_at,completed_at,revision"
        ),
        {
            "organization_id": command.organization_id,
            "entry_id": command.queue_entry_id,
            "resource_id": command.resource_id,
            "location_id": command.location_id,
            "workload_id": command.actual_workload_classification_id,
            "started_at": started_at,
        },
    )
    return session_from_row(row.mappings().one())
