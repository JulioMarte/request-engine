from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_mapping(
    session: AsyncSession, organization_id: UUID, offering_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, service_classification_id, revision, status
                    FROM request_engine.offering_service_classifications
                    WHERE organization_id = :organization_id
                      AND offering_id = :offering_id
                      AND status = 'active'
                    FOR UPDATE
                    """
                ),
                {"organization_id": organization_id, "offering_id": offering_id},
            )
        )
        .mappings()
        .first()
    )


async def revoke_mapping(
    session: AsyncSession, organization_id: UUID, mapping_id: UUID
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
