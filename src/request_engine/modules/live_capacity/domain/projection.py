from datetime import datetime, timedelta

from request_engine.modules.live_capacity.contracts.projection import (
    CapacityInterval,
    LiveCapacityProjection,
    ProjectedWorkItem,
    ProjectionReason,
    ProjectionState,
    ProjectionWorkItem,
)


def _usable_intervals(
    observed_at: datetime, intervals: tuple[CapacityInterval, ...]
) -> tuple[CapacityInterval, ...]:
    usable: list[CapacityInterval] = []
    for interval in sorted(intervals, key=lambda item: item.starts_at):
        starts_at = max(interval.starts_at, observed_at)
        if interval.ends_at > starts_at:
            usable.append(CapacityInterval(starts_at, interval.ends_at))
    return tuple(usable)


def _project_one(
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


def project_live_capacity(
    *,
    observed_at: datetime,
    intervals: tuple[CapacityInterval, ...],
    work_items: tuple[ProjectionWorkItem, ...],
    has_open_interruption: bool = False,
    has_open_resource_activity: bool = False,
) -> LiveCapacityProjection:
    usable = _usable_intervals(observed_at, intervals)
    operational_seconds = sum(
        int((item.ends_at - item.starts_at).total_seconds()) for item in usable
    )
    blockers: list[ProjectionReason] = []
    if has_open_interruption:
        blockers.append(ProjectionReason.OPEN_INTERRUPTION)
    if has_open_resource_activity:
        blockers.append(ProjectionReason.OPEN_RESOURCE_ACTIVITY)
    if blockers:
        return LiveCapacityProjection(
            observed_at,
            ProjectionState.INDETERMINATE,
            tuple(blockers),
            operational_seconds,
            None,
            None,
            None,
            (),
        )

    projected: list[ProjectedWorkItem] = []
    cursor = observed_at
    total = 0
    unknown = False
    for item in work_items:
        if item.duration_seconds is None:
            unknown = True
            projected.append(ProjectedWorkItem(item.key, None, None, None, item.source))
            continue
        remaining = max(item.duration_seconds - item.active_service_seconds, 0)
        total += remaining
        if unknown:
            projected.append(ProjectedWorkItem(item.key, None, None, remaining, item.source))
            continue
        start, end, cursor = _project_one(cursor, remaining, usable)
        projected.append(ProjectedWorkItem(item.key, start, end, remaining, item.source))

    reasons: list[ProjectionReason] = []
    if unknown:
        reasons.append(ProjectionReason.UNKNOWN_WORKLOAD_DURATION)
    if not usable:
        reasons.append(ProjectionReason.NO_REMAINING_AVAILABILITY)
    state = ProjectionState.PARTIAL if unknown else ProjectionState.KNOWN
    known_total = None if unknown else total
    end_at = projected[-1].estimated_end if projected and not unknown else None
    headroom = None if known_total is None else operational_seconds - known_total
    return LiveCapacityProjection(
        observed_at,
        state,
        tuple(reasons),
        operational_seconds,
        known_total,
        end_at,
        headroom,
        tuple(projected),
    )
