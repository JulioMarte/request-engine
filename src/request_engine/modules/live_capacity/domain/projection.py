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


def _scheduled_capacity(
    operational_seconds: int,
    scheduled_work_items: tuple[ProjectionWorkItem, ...],
) -> tuple[int | None, int | None]:
    if any(item.duration_seconds is None for item in scheduled_work_items):
        return None, None
    committed = sum(item.duration_seconds or 0 for item in scheduled_work_items)
    return committed, operational_seconds - committed


def project_live_capacity(
    *,
    observed_at: datetime,
    intervals: tuple[CapacityInterval, ...],
    work_items: tuple[ProjectionWorkItem, ...],
    scheduled_work_items: tuple[ProjectionWorkItem, ...] = (),
    has_open_interruption: bool = False,
    has_open_resource_activity: bool = False,
) -> LiveCapacityProjection:
    usable = _usable_intervals(observed_at, intervals)
    operational_seconds = sum(
        int((item.ends_at - item.starts_at).total_seconds()) for item in usable
    )
    scheduled_committed, scheduled_headroom = _scheduled_capacity(
        operational_seconds, scheduled_work_items
    )
    blockers: list[ProjectionReason] = []
    if has_open_interruption:
        blockers.append(ProjectionReason.OPEN_INTERRUPTION)
    if has_open_resource_activity:
        blockers.append(ProjectionReason.OPEN_RESOURCE_ACTIVITY)
    if blockers:
        return LiveCapacityProjection(
            observed_at=observed_at,
            state=ProjectionState.INDETERMINATE,
            reasons=tuple(blockers),
            remaining_operational_seconds=operational_seconds,
            projected_remaining_workload_seconds=None,
            projected_end_at=None,
            live_headroom_seconds=None,
            items=(),
            scheduled_committed_workload_seconds=scheduled_committed,
            scheduled_headroom_seconds=scheduled_headroom,
            live_intake_headroom_seconds=None,
            live_vs_scheduled_headroom_delta_seconds=None,
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
    live_headroom = None if known_total is None else operational_seconds - known_total
    delta = (
        None
        if live_headroom is None or scheduled_headroom is None
        else live_headroom - scheduled_headroom
    )
    return LiveCapacityProjection(
        observed_at=observed_at,
        state=state,
        reasons=tuple(reasons),
        remaining_operational_seconds=operational_seconds,
        projected_remaining_workload_seconds=known_total,
        projected_end_at=end_at,
        live_headroom_seconds=live_headroom,
        items=tuple(projected),
        scheduled_committed_workload_seconds=scheduled_committed,
        scheduled_headroom_seconds=scheduled_headroom,
        live_intake_headroom_seconds=live_headroom,
        live_vs_scheduled_headroom_delta_seconds=delta,
    )
