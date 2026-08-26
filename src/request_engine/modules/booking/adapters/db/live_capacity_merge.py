from request_engine.modules.booking.contracts.live_capacity import (
    OperationalAvailabilityInterval,
)


def merge_operational_intervals(
    intervals: list[OperationalAvailabilityInterval],
) -> tuple[OperationalAvailabilityInterval, ...]:
    merged: list[OperationalAvailabilityInterval] = []
    for interval in sorted(intervals, key=lambda item: (item.starts_at, item.ends_at)):
        if not merged or interval.starts_at > merged[-1].ends_at:
            merged.append(interval)
            continue
        previous = merged[-1]
        if interval.ends_at > previous.ends_at:
            merged[-1] = OperationalAvailabilityInterval(
                starts_at=previous.starts_at,
                ends_at=interval.ends_at,
            )
    return tuple(merged)
