from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.delivery.contracts.live_capacity import HistoricalServiceObservation


async def read_completed_history(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    workload_classification_id: UUID,
    observed_at: datetime,
    lookback_days: int,
    limit: int,
    resource_specific: bool,
) -> tuple[HistoricalServiceObservation, ...]:
    if lookback_days <= 0 or limit <= 0:
        return ()
    resource_clause = "AND s.resource_id = :resource_id" if resource_specific else ""
    rows = (
        (
            await session.execute(
                text(
                    f"""
                    SELECT s.id, s.resource_id, s.actual_workload_classification_id,
                           s.completed_at,
                           GREATEST(0, extract(epoch FROM (s.completed_at - s.started_at))
                             - COALESCE((
                                 SELECT sum(extract(epoch FROM (i.ended_at - i.started_at)))
                                 FROM request_engine.service_session_interruptions i
                                 WHERE i.organization_id = s.organization_id
                                   AND i.service_session_id = s.id
                             ), 0))::bigint AS active_service_seconds
                    FROM request_engine.service_sessions s
                    WHERE s.organization_id = :organization_id
                      {resource_clause}
                      AND s.actual_workload_classification_id = :workload_classification_id
                      AND s.status = 'completed'
                      AND s.completed_at <= :observed_at
                      AND s.completed_at >= :observed_at - make_interval(days => :lookback_days)
                    ORDER BY s.completed_at DESC, s.id DESC
                    LIMIT :limit
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "workload_classification_id": workload_classification_id,
                    "observed_at": observed_at,
                    "lookback_days": lookback_days,
                    "limit": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        HistoricalServiceObservation(
            service_session_id=cast(UUID, row["id"]),
            resource_id=cast(UUID, row["resource_id"]),
            workload_classification_id=cast(UUID, row["actual_workload_classification_id"]),
            completed_at=cast(datetime, row["completed_at"]),
            active_service_seconds=cast(int, row["active_service_seconds"]),
        )
        for row in rows
        if cast(int, row["active_service_seconds"]) > 0
    )
