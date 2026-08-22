from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession


async def active_classification(session: AsyncSession, key: str) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, classification_key
                    FROM request_engine.service_classifications
                    WHERE classification_key = :key AND status = 'active'
                    FOR SHARE
                    """
                ),
                {"key": key},
            )
        )
        .mappings()
        .first()
    )


async def lock_offering(session: AsyncSession, organization_id: UUID, offering_id: UUID) -> bool:
    value = (
        await session.execute(
            text(
                """
                SELECT 1 FROM request_engine.offerings
                WHERE organization_id = :organization_id AND id = :offering_id
                FOR SHARE
                """
            ),
            {"organization_id": organization_id, "offering_id": offering_id},
        )
    ).scalar_one_or_none()
    return value is not None


async def current_mapping(
    session: AsyncSession, organization_id: UUID, offering_id: UUID
) -> RowMapping | None:
    return (
        (
            await session.execute(
                text(
                    """
                    SELECT id, service_classification_id, revision
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


async def insert_mapping(
    session: AsyncSession, organization_id: UUID, offering_id: UUID, classification_id: UUID
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.offering_service_classifications (
                        organization_id, offering_id, service_classification_id
                    ) VALUES (:organization_id, :offering_id, :classification_id)
                    RETURNING id, revision
                    """
                ),
                {
                    "organization_id": organization_id,
                    "offering_id": offering_id,
                    "classification_id": classification_id,
                },
            )
        )
        .mappings()
        .one()
    )


async def replace_mapping(
    session: AsyncSession, organization_id: UUID, mapping_id: UUID, classification_id: UUID
) -> RowMapping:
    return (
        (
            await session.execute(
                text(
                    """
                    UPDATE request_engine.offering_service_classifications
                    SET service_classification_id = :classification_id
                    WHERE id = :id AND organization_id = :organization_id
                    RETURNING id, revision
                    """
                ),
                {
                    "classification_id": classification_id,
                    "id": mapping_id,
                    "organization_id": organization_id,
                },
            )
        )
        .mappings()
        .one()
    )
