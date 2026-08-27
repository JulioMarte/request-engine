from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryCommitmentCheckpoint,
)


async def require_recovery_source_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    service_queue_id: UUID,
    expected_revision: int,
) -> None:
    current = cast(
        int,
        (
            await session.execute(
                text(
                    "SELECT request_cmd.lock_recovery_source_revision("
                    ":organization_id, :service_queue_id)"
                ),
                {
                    "organization_id": organization_id,
                    "service_queue_id": service_queue_id,
                },
            )
        ).scalar_one(),
    )
    if current != expected_revision:
        raise RecoveryBookingConflict("recovery live source revision changed")


async def require_source_resource_revision(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    expected_revision: int,
) -> None:
    sql = """
        SELECT availability_revision
        FROM request_engine.resources
        WHERE organization_id = :organization_id AND id = :resource_id
    """
    current = cast(
        int,
        (
            await session.execute(
                text(sql),
                {"organization_id": organization_id, "resource_id": resource_id},
            )
        ).scalar_one(),
    )
    if current != expected_revision:
        raise RecoveryBookingConflict("recovery source Resource revision changed")


async def require_source_commitments(
    session: AsyncSession,
    *,
    organization_id: UUID,
    resource_id: UUID,
    location_id: UUID,
    observed_at: datetime,
    horizon_end: datetime,
    expected: tuple[RecoveryCommitmentCheckpoint, ...],
) -> None:
    sql = """
        SELECT DISTINCT r.id, r.revision,
               lower(r.during) AS starts_at, upper(r.during) AS ends_at
        FROM request_engine.reservations r
        JOIN request_engine.capacity_claims c
          ON c.organization_id = r.organization_id AND c.reservation_id = r.id
        WHERE r.organization_id = :organization_id
          AND r.location_id = :location_id AND r.status = 'confirmed'
          AND c.resource_id = :resource_id AND c.status = 'active'
          AND lower(r.during) >= :observed_at AND lower(r.during) < :horizon_end
        ORDER BY lower(r.during), r.id
    """
    rows = (
        (
            await session.execute(
                text(sql),
                {
                    "organization_id": organization_id,
                    "resource_id": resource_id,
                    "location_id": location_id,
                    "observed_at": observed_at,
                    "horizon_end": horizon_end,
                },
            )
        )
        .mappings()
        .all()
    )
    current = tuple(
        RecoveryCommitmentCheckpoint(
            reservation_id=cast(UUID, row["id"]),
            revision=cast(int, row["revision"]),
            starts_at=cast(datetime, row["starts_at"]),
            ends_at=cast(datetime, row["ends_at"]),
        )
        for row in rows
    )
    if current != expected:
        raise RecoveryBookingConflict("recovery source commitment set changed")


async def require_current_recovery_window(
    session: AsyncSession,
    *,
    target_start_at: datetime,
    source_horizon_end: datetime,
) -> None:
    db_now = cast(
        datetime,
        (await session.execute(text("SELECT clock_timestamp()"))).scalar_one(),
    )
    if db_now >= source_horizon_end or target_start_at <= db_now:
        raise RecoveryBookingConflict("recovery proposal temporal window is stale")
