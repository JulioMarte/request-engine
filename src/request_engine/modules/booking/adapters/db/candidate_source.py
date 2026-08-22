from collections.abc import Sequence
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def load(
    session: AsyncSession,
    *,
    organization_id: UUID,
    offering_version_id: UUID,
) -> Sequence[RowMapping]:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT
                        rr.id AS requirement_id,
                        rr.ordinal,
                        rr.quantity,
                        r.id AS resource_id,
                        r.location_id,
                        r.capacity_model,
                        r.capacity_units,
                        r.availability_revision,
                        COALESCE(l.timezone, 'UTC') AS default_timezone
                    FROM request_engine.offering_resource_requirements rr
                    JOIN request_engine.resource_capability_assignments a
                      ON a.organization_id = rr.organization_id
                     AND a.capability_id = rr.capability_id
                    JOIN request_engine.resources r
                      ON r.organization_id = a.organization_id
                     AND r.id = a.resource_id
                    LEFT JOIN request_engine.locations l
                      ON l.organization_id = r.organization_id
                     AND l.id = r.location_id
                    WHERE rr.organization_id = :organization_id
                      AND rr.offering_version_id = :offering_version_id
                      AND r.active
                    ORDER BY rr.ordinal, r.id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_version_id": offering_version_id,
                },
            )
        )
        .mappings()
        .all()
    )


def apply_resource_preference(
    rows: Sequence[RowMapping],
    resource_id: UUID,
) -> tuple[RowMapping, ...]:
    preferred_requirements = {
        cast(UUID, row["requirement_id"])
        for row in rows
        if cast(UUID, row["resource_id"]) == resource_id
    }
    if not preferred_requirements:
        return ()
    return tuple(
        row
        for row in rows
        if cast(UUID, row["requirement_id"]) not in preferred_requirements
        or cast(UUID, row["resource_id"]) == resource_id
    )
