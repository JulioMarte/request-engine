from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def insert_publication(
    session: AsyncSession,
    *,
    organization_id: UUID,
    offering_id: UUID,
    location_id: UUID,
    resource_id: UUID | None,
    effective_start: datetime,
    effective_end: datetime | None,
    provider_visibility: str,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.discovery_publications (
                        organization_id, offering_id, location_id, resource_id,
                        effective_during, provider_visibility
                    ) VALUES (
                        :organization_id, :offering_id, :location_id, :resource_id,
                        tstzrange(:effective_start, :effective_end, '[)'), :provider_visibility
                    )
                    RETURNING id, revision
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_id": offering_id,
                    "location_id": location_id,
                    "resource_id": resource_id,
                    "effective_start": effective_start,
                    "effective_end": effective_end,
                    "provider_visibility": provider_visibility,
                },
            )
        )
        .mappings()
        .one()
    )


async def lock_publication(
    session: AsyncSession, organization_id: UUID, publication_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, offering_id, location_id, resource_id,
                           lower(effective_during) AS effective_start,
                           upper(effective_during) AS effective_end,
                           provider_visibility, status, revision
                    FROM request_engine.discovery_publications
                    WHERE organization_id = :organization_id AND id = :publication_id
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "publication_id": publication_id},
            )
        )
        .mappings()
        .first()
    )


async def revoke_publication(
    session: AsyncSession, organization_id: UUID, publication_id: UUID
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.discovery_publications
                    SET status = 'revoked'
                    WHERE organization_id = :organization_id AND id = :publication_id
                    RETURNING revision
                    """
                ),
                {"organization_id": organization_id, "publication_id": publication_id},
            )
        )
        .mappings()
        .one()
    )
