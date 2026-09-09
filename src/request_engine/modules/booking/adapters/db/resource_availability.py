from collections import defaultdict
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    ExceptionKind,
    LiveCapacityClaim,
)


async def load_resource_exceptions(
    session: AsyncSession,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
    window_start: datetime,
    window_end: datetime,
) -> dict[UUID, tuple[AvailabilityException, ...]]:
    if not resource_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT resource_id, lower(during) AS start_at, upper(during) AS end_at,
                           exception_kind
                    FROM request_engine.schedule_exceptions
                    WHERE organization_id = :organization_id
                      AND resource_id = ANY(CAST(:resource_ids AS uuid[]))
                      AND during && tstzrange(:window_start, :window_end, '[)')
                    ORDER BY resource_id, lower(during), id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_ids": [str(value) for value in resource_ids],
                    "window_start": window_start,
                    "window_end": window_end,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[AvailabilityException]] = defaultdict(list)
    for row in rows:
        grouped[cast(UUID, row["resource_id"])].append(
            AvailabilityException(
                start_at=cast(datetime, row["start_at"]),
                end_at=cast(datetime, row["end_at"]),
                kind=ExceptionKind(cast(str, row["exception_kind"])),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}


async def load_live_capacity_claims(
    session: AsyncSession,
    organization_id: UUID,
    resource_ids: tuple[UUID, ...],
    window_start: datetime,
    window_end: datetime,
    *,
    exclude_reservation_id: UUID | None = None,
) -> dict[UUID, tuple[LiveCapacityClaim, ...]]:
    if not resource_ids:
        return {}
    rows = (
        (
            await session.execute(
                text(
                    """
                    SELECT c.resource_id,
                           lower(c.during) AS start_at,
                           upper(c.during) AS end_at,
                           c.quantity
                    FROM request_engine.capacity_claims c
                    LEFT JOIN request_engine.reservations r
                      ON r.organization_id = c.organization_id
                     AND r.id = c.reservation_id
                    LEFT JOIN request_engine.capacity_holds h
                      ON h.organization_id = c.organization_id
                     AND h.id = c.hold_id
                    WHERE c.organization_id = :organization_id
                      AND c.resource_id = ANY(CAST(:resource_ids AS uuid[]))
                      AND c.status = 'active'
                      AND c.during && tstzrange(:window_start, :window_end, '[)')
                      AND (
                          CAST(:exclude_reservation_id AS uuid) IS NULL
                          OR c.reservation_id IS DISTINCT FROM
                             CAST(:exclude_reservation_id AS uuid)
                      )
                      AND (
                          (c.reservation_id IS NOT NULL AND r.status = 'confirmed')
                          OR (
                              c.reservation_id IS NULL
                              AND h.status = 'active'
                              AND h.expires_at > clock_timestamp()
                          )
                      )
                    ORDER BY c.resource_id, lower(c.during), c.id
                    """
                ),
                {
                    "organization_id": organization_id,
                    "resource_ids": [str(value) for value in resource_ids],
                    "window_start": window_start,
                    "window_end": window_end,
                    "exclude_reservation_id": exclude_reservation_id,
                },
            )
        )
        .mappings()
        .all()
    )
    grouped: dict[UUID, list[LiveCapacityClaim]] = defaultdict(list)
    for row in rows:
        grouped[cast(UUID, row["resource_id"])].append(
            LiveCapacityClaim(
                start_at=cast(datetime, row["start_at"]),
                end_at=cast(datetime, row["end_at"]),
                quantity=cast(int, row["quantity"]),
            )
        )
    return {key: tuple(value) for key, value in grouped.items()}
