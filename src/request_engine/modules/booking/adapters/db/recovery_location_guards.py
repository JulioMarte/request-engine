from typing import cast
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.contracts.recovery import (
    RecoveryBookingConflict,
    RecoveryTargetUnavailable,
)


async def lock_recovery_locations(
    session: AsyncSession,
    *,
    organization_id: UUID,
    source_location_id: UUID,
    expected_source_revision: int,
    target_location_id: UUID | None,
) -> None:
    ids = {source_location_id}
    if target_location_id is not None:
        ids.add(target_location_id)
    location_ids = tuple(sorted(ids, key=str))
    sql = """
        SELECT id, active, operational_revision
        FROM request_engine.locations
        WHERE organization_id = :organization_id
          AND id = ANY(CAST(:location_ids AS uuid[]))
        ORDER BY id
        FOR UPDATE
    """
    rows = (
        (
            await session.execute(
                text(sql),
                {
                    "organization_id": organization_id,
                    "location_ids": [str(value) for value in location_ids],
                },
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(location_ids):
        raise RecoveryBookingConflict("recovery Location provenance no longer exists")
    by_id = {cast(UUID, row["id"]): row for row in rows}
    source = by_id[source_location_id]
    if cast(int, source["operational_revision"]) != expected_source_revision:
        raise RecoveryBookingConflict("recovery source Location revision changed")
    if any(row["active"] is not True for row in rows):
        raise RecoveryTargetUnavailable("recovery source or target Location is inactive")
