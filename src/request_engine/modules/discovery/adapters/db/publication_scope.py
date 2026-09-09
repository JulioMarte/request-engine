from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def validate_scope(
    session: AsyncSession,
    *,
    organization_id: UUID,
    offering_id: UUID,
    location_id: UUID,
    resource_id: UUID | None,
    effective_start: datetime,
    effective_end: datetime | None,
) -> bool:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT
                        EXISTS (
                            SELECT 1 FROM request_engine.offerings o
                            WHERE o.organization_id = :organization_id
                              AND o.id = :offering_id AND o.active
                        ) AS offering_ok,
                        EXISTS (
                            SELECT 1 FROM request_engine.locations l
                            WHERE l.organization_id = :organization_id
                              AND l.id = :location_id AND l.active
                        ) AS location_ok,
                        (CAST(:resource_id AS uuid) IS NULL OR EXISTS (
                            SELECT 1
                            FROM request_engine.resources r
                            JOIN request_engine.resource_location_assignments a
                              ON a.organization_id = r.organization_id
                             AND a.resource_id = r.id
                             AND a.location_id = :location_id
                             AND a.status = 'active'
                             AND a.effective_during && tstzrange(
                                 :effective_start, :effective_end, '[)'
                             )
                            WHERE r.organization_id = :organization_id
                              AND r.id = CAST(:resource_id AS uuid)
                              AND r.active
                        )) AS resource_ok,
                        EXISTS (
                            SELECT 1
                            FROM request_engine.offering_service_classifications m
                            JOIN LATERAL request_engine.lookup_service_classification(
                                m.service_classification_id
                            ) sc ON sc.status = 'active'
                            WHERE m.organization_id = :organization_id
                              AND m.offering_id = :offering_id
                              AND m.status = 'active'
                        ) AS mapping_ok
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_id": offering_id,
                    "location_id": location_id,
                    "resource_id": resource_id,
                    "effective_start": effective_start,
                    "effective_end": effective_end,
                },
            )
        )
        .mappings()
        .one()
    )
    checks = ("offering_ok", "location_ok", "resource_ok", "mapping_ok")
    return all(bool(row[key]) for key in checks)
