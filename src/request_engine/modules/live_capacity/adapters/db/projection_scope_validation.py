from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.application.errors import InvalidProjectionConfiguration


async def validate_projection_scope(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    resource_id: UUID,
    location_id: UUID,
) -> None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT q.location_id AS queue_location_id,
                           r.active AS resource_active,
                           l.active AS location_active
                    FROM request_engine.service_queues q
                    JOIN request_engine.resources r
                      ON r.organization_id = q.organization_id
                     AND r.id = :resource_id
                    JOIN request_engine.locations l
                      ON l.organization_id = q.organization_id
                     AND l.id = :location_id
                    WHERE q.organization_id = :organization_id
                      AND q.id = :service_queue_id
                    FOR SHARE OF q, r, l
                    """
                ),
                {
                    "organization_id": organization_id,
                    "service_queue_id": service_queue_id,
                    "resource_id": resource_id,
                    "location_id": location_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["resource_active"] or not row["location_active"]:
        raise InvalidProjectionConfiguration(service_queue_id)
    queue_location_id = cast(UUID | None, row["queue_location_id"])
    if queue_location_id is not None and queue_location_id != location_id:
        raise InvalidProjectionConfiguration(service_queue_id)
