from typing import cast
from uuid import UUID

from sqlalchemy import text

from request_engine.modules.live_capacity.application.projection_snapshot import ProjectionSnapshot
from request_engine.platform.db.read_snapshot import postgres_snapshot_session
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


async def read_recovery_revisions(
    read_snapshot: ReadSnapshot,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    snapshot: ProjectionSnapshot,
) -> tuple[int, int, int]:
    session = postgres_snapshot_session(read_snapshot)
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT r.availability_revision,
                           l.operational_revision,
                           request_read.recovery_source_revision(
                               :organization_id,
                               :service_queue_id
                           ) AS recovery_source_revision
                    FROM request_engine.resources r
                    JOIN request_engine.locations l
                      ON l.organization_id = r.organization_id
                     AND l.id = :location_id
                    WHERE r.organization_id = :organization_id
                      AND r.id = :resource_id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "service_queue_id": service_queue_id,
                    "resource_id": snapshot.policy.resource_id,
                    "location_id": snapshot.policy.location_id,
                },
            )
        )
        .mappings()
        .one()
    )
    return (
        cast(int, row["availability_revision"]),
        cast(int, row["operational_revision"]),
        cast(int, row["recovery_source_revision"]),
    )
