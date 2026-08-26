from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.live_capacity.adapters.db.policy_common import projection_scope_from_row
from request_engine.modules.live_capacity.contracts.policy import ProjectionScopePolicy


async def load_active_projection_scope(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
) -> ProjectionScopePolicy | None:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT id, service_queue_id, resource_id, location_id, active, revision
                    FROM request_engine.live_capacity_projection_policies
                    WHERE organization_id = :organization_id
                      AND service_queue_id = :service_queue_id
                      AND active
                    """
                ),
                {
                    "organization_id": organization_id,
                    "service_queue_id": service_queue_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return projection_scope_from_row(row) if row is not None else None


async def load_configured_estimates(
    session: AsyncSession,
    *,
    organization_id: UUID,
    workload_ids: tuple[UUID, ...],
) -> dict[UUID, int]:
    if not workload_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT workload_classification_id, duration_seconds
                    FROM request_engine.live_capacity_workload_estimate_policies
                    WHERE organization_id = :organization_id
                      AND active
                      AND workload_classification_id = ANY(CAST(:workload_ids AS uuid[]))
                    """
                ),
                {
                    "organization_id": organization_id,
                    "workload_ids": [str(value) for value in workload_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    return {
        cast(UUID, row["workload_classification_id"]): cast(int, row["duration_seconds"])
        for row in rows
    }
