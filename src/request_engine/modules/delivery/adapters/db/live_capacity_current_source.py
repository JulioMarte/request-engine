from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.contracts.live_capacity import (
    ActiveServiceProjectionFact,
    DeliveryProjectionSnapshot,
    ResourceOccupationProjectionFact,
)


async def read_projection_delivery(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    observed_at: datetime,
) -> DeliveryProjectionSnapshot:
    service = (
        (
            await session.execute(
                text(
                    """
                    SELECT s.id, s.queue_entry_id, s.resource_id, s.location_id,
                           s.status, s.actual_workload_classification_id, s.started_at,
                           GREATEST(0, extract(epoch FROM (:observed_at - s.started_at))
                             - COALESCE((
                                 SELECT sum(extract(epoch FROM (
                                     COALESCE(i.ended_at, :observed_at) - i.started_at
                                 )))
                                 FROM request_engine.service_session_interruptions i
                                 WHERE i.organization_id = s.organization_id
                                   AND i.service_session_id = s.id
                             ), 0))::bigint AS active_service_seconds,
                           EXISTS (
                               SELECT 1
                               FROM request_engine.service_session_interruptions i
                               WHERE i.organization_id = s.organization_id
                                 AND i.service_session_id = s.id
                                 AND i.ended_at IS NULL
                           ) AS has_open_interruption
                    FROM request_engine.service_sessions s
                    WHERE s.organization_id = :organization_id
                      AND s.resource_id = :resource_id
                      AND s.location_id = :location_id
                      AND s.status IN ('active','paused')
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "location_id": location_id,
                    "observed_at": observed_at,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    activity = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, resource_id, location_id, started_at, ended_at
                    FROM request_engine.resource_activities
                    WHERE organization_id = :organization_id
                      AND resource_id = :resource_id
                      AND (location_id IS NULL OR location_id = :location_id)
                      AND ended_at IS NULL
                    ORDER BY started_at, id
                    LIMIT 1
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "location_id": location_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    active_service = None
    if service is not None:
        active_service = ActiveServiceProjectionFact(
            service_session_id=cast(UUID, service["id"]),
            queue_entry_id=cast(UUID, service["queue_entry_id"]),
            resource_id=cast(UUID, service["resource_id"]),
            location_id=cast(UUID, service["location_id"]),
            status=cast(str, service["status"]),
            actual_workload_classification_id=cast(
                UUID | None, service["actual_workload_classification_id"]
            ),
            started_at=cast(datetime, service["started_at"]),
            active_service_seconds=cast(int, service["active_service_seconds"]),
            has_open_interruption=cast(bool, service["has_open_interruption"]),
        )
    open_activity = None
    if activity is not None:
        open_activity = ResourceOccupationProjectionFact(
            resource_activity_id=cast(UUID, activity["id"]),
            resource_id=cast(UUID, activity["resource_id"]),
            location_id=cast(UUID | None, activity["location_id"]),
            started_at=cast(datetime, activity["started_at"]),
            has_known_end=activity["ended_at"] is not None,
        )
    return DeliveryProjectionSnapshot(observed_at, active_service, open_activity)
