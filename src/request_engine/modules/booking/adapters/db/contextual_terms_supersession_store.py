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
) -> tuple[UUID, UUID, UUID]:
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
    await session.execute(
        text(
            "SELECT id FROM request_engine.resources "
            "WHERE organization_id=:o AND id=:r AND active FOR UPDATE"
        ),
        {"o": organization_id, "r": resource_id},
    )
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
    return assignment_id, cast(UUID, row["offering_version_id"]), resource_id


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


async def cutover_and_insert(
    session: AsyncSession,
    *,
    organization_id: UUID,
    current_terms_id: UUID,
    assignment_id: UUID,
    offering_version_id: UUID,
    cutover: datetime,
    previous_end: datetime | None,
    amount: object,
    currency: str | None,
    duration: int | None,
    bookable: bool,
) -> tuple[UUID, int]:
    await session.execute(
        text(
            "UPDATE request_engine.booking_context_terms "
            "SET effective_during=tstzrange(lower(effective_during), :cutover, '[)') "
            "WHERE organization_id=:o AND id=:t"
        ),
        {"cutover": cutover, "o": organization_id, "t": current_terms_id},
    )
    row = (
        (
            await session.execute(
                text(
                    """
                    INSERT INTO request_engine.booking_context_terms (
                        organization_id, resource_location_assignment_id,
                        offering_version_id, effective_during, amount, currency,
                        planned_duration_minutes, bookable
                    ) VALUES (
                        :o, :a, :v, tstzrange(:cutover, :ends_at, '[)'),
                        :amount, :currency, :duration, :bookable
                    ) RETURNING id, revision
                    """
                ),
                {
                    "o": organization_id,
                    "a": assignment_id,
                    "v": offering_version_id,
                    "cutover": cutover,
                    "ends_at": previous_end,
                    "amount": amount,
                    "currency": currency,
                    "duration": duration,
                    "bookable": bookable,
                },
            )
        )
        .mappings()
        .one()
    )
    return cast(UUID, row["id"]), cast(int, row["revision"])
