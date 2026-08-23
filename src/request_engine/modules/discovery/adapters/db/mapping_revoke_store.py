from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_mapping(
    session: AsyncSession,
    organization_id: UUID,
    offering_id: UUID,
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT m.id, m.service_classification_id, m.revision, m.status,
                           sc.classification_key
                    FROM request_engine.offering_service_classifications m
                    JOIN LATERAL request_engine.lookup_service_classification(
                        m.service_classification_id
                    ) sc ON true
                    WHERE m.organization_id = :organization_id
                      AND m.offering_id = :offering_id
                      AND m.status = 'active'
                    FOR UPDATE OF m
                    """
                ),
                {"organization_id": organization_id, "offering_id": offering_id},
            )
        )
        .mappings()
        .first()
    )


async def revoke_mapping(
    session: AsyncSession,
    organization_id: UUID,
    mapping_id: UUID,
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.offering_service_classifications
                    SET status = 'revoked'
                    WHERE organization_id = :organization_id AND id = :mapping_id
                    RETURNING revision
                    """
                ),
                {"organization_id": organization_id, "mapping_id": mapping_id},
            )
        )
        .mappings()
        .one()
    )
