from datetime import datetime, timedelta

from request_engine.modules.live_capacity.contracts.projection import CapacityInterval


def usable_intervals(
    observed_at: datetime,
    intervals: tuple[CapacityInterval, ...],
) -> tuple[CapacityInterval, ...]:
    usable: list[CapacityInterval] = []
    for interval in sorted(intervals, key=lambda item: item.starts_at):
        starts_at = max(interval.starts_at, observed_at)
        if interval.ends_at > starts_at:
            usable.append(CapacityInterval(starts_at, interval.ends_at))
    return tuple(usable)


def project_one(
    cursor: datetime,
    remaining_seconds: int,
    intervals: tuple[CapacityInterval, ...],
) -> tuple[datetime | None, datetime | None, datetime]:
    start: datetime | None = None
    seconds_left = remaining_seconds
    current = cursor
    for interval in intervals:
        position = max(current, interval.starts_at)
        if position >= interval.ends_at:
            continue
        if start is None:
            start = position
        available = int((interval.ends_at - position).total_seconds())
        if seconds_left <= available:
            end = position + timedelta(seconds=seconds_left)
            return start, end, end
        seconds_left -= available
        current = interval.ends_at
    return start, None, current
