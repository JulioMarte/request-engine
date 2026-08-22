from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


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
                        organization_id,
                        resource_location_assignment_id,
                        offering_version_id,
                        effective_during,
                        amount,
                        currency,
                        planned_duration_minutes,
                        bookable
                    ) VALUES (
                        :o,
                        :a,
                        :v,
                        tstzrange(:cutover, :ends_at, '[)'),
                        :amount,
                        :currency,
                        :duration,
                        :bookable
                    )
                    RETURNING id, revision
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
