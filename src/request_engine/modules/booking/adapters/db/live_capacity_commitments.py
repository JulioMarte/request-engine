from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.domain.availability import LiveCapacityClaim


async def load_unplanned_live_claims(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    observed_at: datetime,
    horizon_end: datetime,
) -> tuple[LiveCapacityClaim, ...]:
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT lower(c.during) AS start_at,
                           upper(c.during) AS end_at,
                           c.quantity
                    FROM request_engine.capacity_claims c
                    JOIN request_engine.capacity_holds h
                      ON h.organization_id = c.organization_id
                     AND h.id = c.hold_id
                    WHERE c.organization_id = :organization_id
                      AND c.resource_id = :resource_id
                      AND c.status = 'active'
                      AND c.reservation_id IS NULL
                      AND h.status = 'active'
                      AND h.expires_at > :observed_at
                      AND c.during && tstzrange(:observed_at, :horizon_end, '[)')
                    ORDER BY lower(c.during), c.id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "observed_at": observed_at,
                    "horizon_end": horizon_end,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        LiveCapacityClaim(
            start_at=cast(datetime, row["start_at"]),
            end_at=cast(datetime, row["end_at"]),
            quantity=cast(int, row["quantity"]),
        )
        for row in rows
    )
