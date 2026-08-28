from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_recovery_source_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
) -> int:
    return (
        await session.execute(
            text(
                "SELECT revision FROM request_engine.recovery_source_revisions "
                "WHERE organization_id=:organization_id "
                "AND service_queue_id=:service_queue_id FOR UPDATE"
            ),
            {"organization_id": organization_id, "service_queue_id": service_queue_id},
        )
    ).scalar_one()
