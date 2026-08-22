from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.application.operational_errors import ContextualConfigurationConflict


async def lock_identity(
    session: AsyncSession,
    *,
    organization_id: UUID,
    terms_id: UUID,
) -> tuple[UUID, UUID]:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT b.resource_location_assignment_id,
                           b.offering_version_id,
                           a.resource_id
                    FROM request_engine.booking_context_terms b
                    JOIN request_engine.resource_location_assignments a
                      ON a.organization_id = b.organization_id
                     AND a.id = b.resource_location_assignment_id
                    WHERE b.organization_id = :organization_id
                      AND b.id = :terms_id
                    """
                ),
                {"organization_id": organization_id, "terms_id": terms_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ContextualConfigurationConflict("BookingContextTerms is missing or foreign")
    assignment_id = cast(UUID, row["resource_location_assignment_id"])
    resource_id = cast(UUID, row["resource_id"])
    resource = (
        await session.execute(
            text(
                "SELECT id FROM request_engine.resources "
                "WHERE organization_id=:o AND id=:r AND active FOR UPDATE"
            ),
            {"o": organization_id, "r": resource_id},
        )
    ).first()
    if resource is None:
        raise ContextualConfigurationConflict("ResourceLocationAssignment is not configurable")
    assignment = (
        await session.execute(
            text(
                "SELECT status FROM request_engine.resource_location_assignments "
                "WHERE organization_id=:o AND id=:a FOR UPDATE"
            ),
            {"o": organization_id, "a": assignment_id},
        )
    ).first()
    if assignment is None or assignment[0] != "active":
        raise ContextualConfigurationConflict("ResourceLocationAssignment is not configurable")
    return assignment_id, cast(UUID, row["offering_version_id"])


async def lock_current_range(
    session: AsyncSession,
    *,
    organization_id: UUID,
    terms_id: UUID,
) -> tuple[datetime, datetime | None, int]:
    row = (
        (
            await session.execute(
                text(
                    """
                    SELECT lower(effective_during) AS starts_at,
                           upper(effective_during) AS ends_at,
                           revision
                    FROM request_engine.booking_context_terms
                    WHERE organization_id=:o AND id=:t
                    FOR UPDATE
                    """
                ),
                {"o": organization_id, "t": terms_id},
            )
        )
        .mappings()
        .one()
    )
    return (
        cast(datetime, row["starts_at"]),
        cast(datetime | None, row["ends_at"]),
        cast(int, row["revision"]),
    )
