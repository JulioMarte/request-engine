from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.live_capacity import PlannedWorkloadFact


async def load_planned_same_day_work(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    observed_at: datetime,
    horizon_end: datetime,
) -> tuple[PlannedWorkloadFact, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT DISTINCT
                           r.id,
                           r.offering_version_id,
                           r.subject_party_id,
                           r.revision,
                           lower(r.during) AS starts_at,
                           upper(r.during) AS ends_at
                    FROM request_engine.reservations r
                    JOIN request_engine.capacity_claims c
                      ON c.organization_id = r.organization_id
                     AND c.reservation_id = r.id
                    WHERE r.organization_id = :organization_id
                      AND r.location_id = :location_id
                      AND r.status = 'confirmed'
                      AND c.resource_id = :resource_id
                      AND c.status = 'active'
                      AND lower(r.during) >= :observed_at
                      AND lower(r.during) < :horizon_end
                    ORDER BY lower(r.during), r.id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "location_id": location_id,
                    "observed_at": observed_at,
                    "horizon_end": horizon_end,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        PlannedWorkloadFact(
            reservation_id=cast(UUID, row["id"]),
            offering_version_id=cast(UUID, row["offering_version_id"]),
            planned_starts_at=cast(datetime, row["starts_at"]),
            planned_ends_at=cast(datetime, row["ends_at"]),
            planned_duration_seconds=max(
                0,
                int(
                    (
                        cast(datetime, row["ends_at"]) - cast(datetime, row["starts_at"])
                    ).total_seconds()
                ),
            ),
            subject_party_id=cast(UUID, row["subject_party_id"]),
            reservation_revision=cast(int, row["revision"]),
        )
        for row in rows
    )
