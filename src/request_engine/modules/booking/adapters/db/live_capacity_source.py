from datetime import datetime, time, timedelta
from typing import cast
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from request_engine.modules.booking.adapters.db.live_capacity_intervals import (
    effective_operational_intervals,
)
from request_engine.modules.booking.adapters.db.live_capacity_merge import (
    merge_operational_intervals,
)
from request_engine.modules.booking.adapters.db.live_capacity_planned_work import (
    load_planned_same_day_work,
)
from request_engine.modules.booking.adapters.db.live_capacity_profiles import (
    load_availability_windows,
)
from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
    ResourceOperationalAvailabilitySnapshot,
)
from request_engine.modules.booking.domain.availability import resolve_local_instant
from request_engine.platform.db.read_snapshot import postgres_snapshot_session
from request_engine.platform.db.read_snapshot_types import ReadSnapshot


class PostgresOperationalAvailabilitySource:
    async def read_operational_availability(
        self,
        snapshot: ReadSnapshot,
        *,
        organization_id: UUID,
        resource_id: UUID,
        location_id: UUID,
        observed_at: datetime,
    ) -> ResourceOperationalAvailabilitySnapshot:
        session = postgres_snapshot_session(snapshot)
        timezone = await _location_timezone(session, organization_id, location_id)
        if timezone is None:
            return _invalid_snapshot(resource_id, location_id, observed_at)
        horizon_end = _next_local_midnight(observed_at, timezone)
        windows = await load_availability_windows(
            session,
            organization_id=organization_id,
            resource_id=resource_id,
            location_id=location_id,
            observed_at=observed_at,
            horizon_end=horizon_end,
        )
        if windows is None:
            return _invalid_snapshot(resource_id, location_id, observed_at, horizon_end)
        intervals: list[OperationalAvailabilityInterval] = []
        for window in windows:
            intervals.extend(
                effective_operational_intervals(
                    profiles=window.profiles,
                    observed_at=observed_at,
                    horizon_end=horizon_end,
                    effective_start=window.effective_start,
                    effective_end=window.effective_end,
                )
            )
        planned = await load_planned_same_day_work(
            session,
            organization_id=organization_id,
            resource_id=resource_id,
            location_id=location_id,
            observed_at=observed_at,
            horizon_end=horizon_end,
        )
        return ResourceOperationalAvailabilitySnapshot(
            resource_id=resource_id,
            location_id=location_id,
            observed_at=observed_at,
            horizon_end=horizon_end,
            configuration_valid=True,
            remaining_intervals=merge_operational_intervals(intervals),
            planned_same_day_work=planned,
        )


async def _location_timezone(
    session: AsyncSession, organization_id: UUID, location_id: UUID
) -> str | None:
    return cast(
        str | None,
        await session.scalar(
            text(
                "SELECT timezone FROM request_engine.locations "
                "WHERE organization_id=:organization_id AND id=:location_id AND active"
            ),
            {"organization_id": organization_id, "location_id": location_id},
        ),
    )


def _next_local_midnight(observed_at: datetime, timezone: str) -> datetime:
    local_date = observed_at.astimezone(ZoneInfo(timezone)).date()
    local_midnight = datetime.combine(local_date + timedelta(days=1), time.min)
    return resolve_local_instant(local_midnight, timezone)


def _invalid_snapshot(
    resource_id: UUID,
    location_id: UUID,
    observed_at: datetime,
    horizon_end: datetime | None = None,
) -> ResourceOperationalAvailabilitySnapshot:
    return ResourceOperationalAvailabilitySnapshot(
        resource_id=resource_id,
        location_id=location_id,
        observed_at=observed_at,
        horizon_end=horizon_end or observed_at,
        configuration_valid=False,
        remaining_intervals=(),
        planned_same_day_work=(),
    )
