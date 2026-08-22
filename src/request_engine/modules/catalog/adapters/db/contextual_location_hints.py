from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def f1_schema_available(session: AsyncSession) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    """
                    SELECT to_regclass('request_engine.resource_location_assignments') IS NOT NULL
                       AND to_regclass('request_engine.offering_version_booking_terms') IS NOT NULL
                    """
                )
            )
        ).scalar_one()
    )


async def eligible_location_ids(
    session: AsyncSession,
    *,
    organization_id: UUID,
    offering_version_id: UUID,
    effective_at: datetime,
) -> tuple[UUID, ...]:
    rows = (
        await session.execute(
            text(
                """
                SELECT l.id
                FROM request_engine.locations l
                WHERE l.organization_id = :organization_id
                  AND l.active
                  AND EXISTS (
                      SELECT 1
                      FROM request_engine.offering_resource_requirements req
                      WHERE req.organization_id = l.organization_id
                        AND req.offering_version_id = :offering_version_id
                  )
                  AND NOT EXISTS (
                      SELECT 1
                      FROM request_engine.offering_resource_requirements req
                      WHERE req.organization_id = l.organization_id
                        AND req.offering_version_id = :offering_version_id
                        AND (
                            SELECT count(DISTINCT r.id)
                            FROM request_engine.resources r
                            JOIN request_engine.resource_capability_assignments rca
                              ON rca.organization_id = r.organization_id
                             AND rca.resource_id = r.id
                             AND rca.capability_id = req.capability_id
                            JOIN request_engine.resource_location_assignments a
                              ON a.organization_id = r.organization_id
                             AND a.resource_id = r.id
                             AND a.location_id = l.id
                             AND a.status = 'active'
                             AND a.effective_during @> CAST(:effective_at AS timestamptz)
                            WHERE r.organization_id = l.organization_id
                              AND r.active
                        ) < req.quantity
                  )
                ORDER BY l.id
                """
            ),
            {
                "organization_id": organization_id,
                "offering_version_id": offering_version_id,
                "effective_at": effective_at.astimezone(UTC),
            },
        )
    ).scalars()
    return tuple(cast(UUID, value) for value in rows)
