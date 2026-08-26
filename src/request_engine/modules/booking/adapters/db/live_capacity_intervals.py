from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
)
from request_engine.modules.booking.domain.availability import (
    RecurringAvailability,
    ResourceAvailability,
    interval_has_resource_capacity,
    interval_is_scheduled_available,
    require_aware_utc,
    resolve_local_instant,
)


def effective_operational_intervals(
    *,
    profiles: tuple[ResourceAvailability, ...],
    observed_at: datetime,
    horizon_end: datetime,
    effective_start: datetime | None = None,
    effective_end: datetime | None = None,
) -> tuple[OperationalAvailabilityInterval, ...]:
    start = require_aware_utc(observed_at, "observed_at")
    end = require_aware_utc(horizon_end, "horizon_end")
    if effective_start is not None:
        start = max(start, require_aware_utc(effective_start, "effective_start"))
    if effective_end is not None:
        end = min(end, require_aware_utc(effective_end, "effective_end"))
    if end <= start or not profiles:
        return ()

    boundaries = {start, end}
    for profile in profiles:
        for schedule in profile.schedules:
            boundaries.update(_schedule_boundaries(schedule, start, end))
        for exception in profile.exceptions:
            if exception.end_at > start and exception.start_at < end:
                boundaries.add(max(start, exception.start_at))
                boundaries.add(min(end, exception.end_at))
        for claim in profile.live_claims:
            if claim.end_at > start and claim.start_at < end:
                boundaries.add(max(start, claim.start_at))
                boundaries.add(min(end, claim.end_at))

    ordered = sorted(boundaries)
    segments: list[OperationalAvailabilityInterval] = []
    for segment_start, segment_end in zip(ordered, ordered[1:], strict=False):
        if segment_end <= segment_start or not _segment_available(
            profiles, segment_start, segment_end
        ):
            continue
        if segments and segments[-1].ends_at == segment_start:
            previous = segments[-1]
            segments[-1] = OperationalAvailabilityInterval(
                starts_at=previous.starts_at,
                ends_at=segment_end,
            )
        else:
            segments.append(OperationalAvailabilityInterval(segment_start, segment_end))
    return tuple(segments)


def _segment_available(
    profiles: tuple[ResourceAvailability, ...], start: datetime, end: datetime
) -> bool:
    return all(
        interval_is_scheduled_available(profile, start_at=start, end_at=end)
        and interval_has_resource_capacity(profile, start_at=start, end_at=end, required_quantity=1)
        for profile in profiles
    )


def _schedule_boundaries(
    schedule: RecurringAvailability,
    start: datetime,
    end: datetime,
) -> set[datetime]:
    zone = ZoneInfo(schedule.timezone)
    current = start.astimezone(zone).date()
    last_date = end.astimezone(zone).date()
    result: set[datetime] = set()
    while current <= last_date:
        if _schedule_applies(schedule, current):
            local_start = datetime.combine(current, schedule.local_start)
            local_end = datetime.combine(current, schedule.local_end)
            start_at = resolve_local_instant(local_start, schedule.timezone)
            end_at = resolve_local_instant(local_end, schedule.timezone)
            if end_at > start and start_at < end:
                result.add(max(start, start_at))
                result.add(min(end, end_at))
        current += timedelta(days=1)
    return result


def _schedule_applies(schedule: RecurringAvailability, value: date) -> bool:
    if value.weekday() != schedule.weekday:
        return False
    if schedule.valid_from is not None and value < schedule.valid_from:
        return False
    return schedule.valid_until is None or value <= schedule.valid_until
