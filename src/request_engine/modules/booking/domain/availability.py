from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class CapacityModel(StrEnum):
    EXCLUSIVE = "exclusive"
    UNITS = "units"


class ExceptionKind(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class LocalTimeResolutionError(ValueError):
    def __init__(self, timezone: str, local_value: datetime, reason: str) -> None:
        super().__init__(f"{local_value.isoformat()} in {timezone} is {reason}")
        self.timezone = timezone
        self.local_value = local_value
        self.reason = reason


@dataclass(frozen=True, slots=True)
class RecurringAvailability:
    weekday: int
    local_start: time
    local_end: time
    timezone: str
    valid_from: date | None
    valid_until: date | None


@dataclass(frozen=True, slots=True)
class AvailabilityException:
    start_at: datetime
    end_at: datetime
    kind: ExceptionKind


@dataclass(frozen=True, slots=True)
class LiveCapacityClaim:
    start_at: datetime
    end_at: datetime
    quantity: int


@dataclass(frozen=True, slots=True)
class ResourceAvailability:
    capacity_model: CapacityModel
    capacity_units: int
    default_timezone: str
    schedules: tuple[RecurringAvailability, ...]
    exceptions: tuple[AvailabilityException, ...]
    live_claims: tuple[LiveCapacityClaim, ...]


@dataclass(frozen=True, slots=True, order=True)
class AvailableInterval:
    start_at: datetime
    end_at: datetime


def require_aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def resolve_local_instant(local_value: datetime, timezone: str) -> datetime:
    """Resolve one local wall-clock instant, rejecting DST gaps and folds."""

    if local_value.tzinfo is not None:
        raise ValueError("local_value must be naive wall-clock time")

    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise LocalTimeResolutionError(timezone, local_value, "in an unknown timezone") from exc

    candidates: set[datetime] = set()
    for fold in (0, 1):
        aware = local_value.replace(tzinfo=zone, fold=fold)
        utc_value = aware.astimezone(UTC)
        roundtrip = utc_value.astimezone(zone).replace(tzinfo=None)
        if roundtrip == local_value:
            candidates.add(utc_value)

    if not candidates:
        raise LocalTimeResolutionError(timezone, local_value, "a nonexistent local time")
    if len(candidates) > 1:
        raise LocalTimeResolutionError(timezone, local_value, "an ambiguous local time")
    return candidates.pop()


def find_resource_intervals(
    profile: ResourceAvailability,
    *,
    window_start: datetime,
    window_end: datetime,
    duration_minutes: int,
    step_minutes: int,
    required_quantity: int,
) -> tuple[AvailableInterval, ...]:
    """Generate advisory intervals for one concrete Resource.

    Recurring schedules are local-wall-clock rules. Explicit unavailable exceptions
    always win; available exceptions may add intervals outside recurring schedules.
    Existing live claims are considered advisory capacity consumption.
    """

    start = require_aware_utc(window_start, "window_start")
    end = require_aware_utc(window_end, "window_end")
    if end <= start:
        raise ValueError("window_end must be after window_start")
    if duration_minutes <= 0:
        raise ValueError("duration_minutes must be positive")
    if step_minutes <= 0:
        raise ValueError("step_minutes must be positive")
    if required_quantity <= 0:
        raise ValueError("required_quantity must be positive")

    duration = timedelta(minutes=duration_minutes)
    step = timedelta(minutes=step_minutes)
    candidates: set[AvailableInterval] = set()

    for schedule in profile.schedules:
        candidates.update(
            _recurring_candidates(
                schedule,
                window_start=start,
                window_end=end,
                duration=duration,
                step=step,
            )
        )

    for exception in profile.exceptions:
        if exception.kind is ExceptionKind.AVAILABLE:
            candidates.update(
                _explicit_available_candidates(
                    exception,
                    window_start=start,
                    window_end=end,
                    duration=duration,
                    step=step,
                )
            )

    result = [
        candidate
        for candidate in candidates
        if not _blocked_by_unavailable_exception(profile.exceptions, candidate)
        and _has_capacity(profile, candidate, required_quantity)
    ]
    return tuple(sorted(result))


def interval_has_resource_capacity(
    profile: ResourceAvailability,
    *,
    start_at: datetime,
    end_at: datetime,
    required_quantity: int,
) -> bool:
    interval = AvailableInterval(
        require_aware_utc(start_at, "start_at"),
        require_aware_utc(end_at, "end_at"),
    )
    if interval.end_at <= interval.start_at:
        return False
    return _has_capacity(profile, interval, required_quantity)


def interval_is_scheduled_available(
    profile: ResourceAvailability,
    *,
    start_at: datetime,
    end_at: datetime,
) -> bool:
    """Revalidate one exact interval against recurring/exception availability."""

    start = require_aware_utc(start_at, "start_at")
    end = require_aware_utc(end_at, "end_at")
    if end <= start:
        return False
    interval = AvailableInterval(start, end)

    if _blocked_by_unavailable_exception(profile.exceptions, interval):
        return False
    if any(
        exception.kind is ExceptionKind.AVAILABLE
        and exception.start_at <= start
        and exception.end_at >= end
        for exception in profile.exceptions
    ):
        return True

    for schedule in profile.schedules:
        try:
            zone = ZoneInfo(schedule.timezone)
        except ZoneInfoNotFoundError as exc:
            local_value = start.replace(tzinfo=None)
            raise LocalTimeResolutionError(
                schedule.timezone,
                local_value,
                "in an unknown timezone",
            ) from exc

        local_start = start.astimezone(zone)
        local_end = end.astimezone(zone)
        if local_start.date() != local_end.date():
            continue
        local_date = local_start.date()
        if local_date.weekday() != schedule.weekday:
            continue
        if schedule.valid_from is not None and local_date < schedule.valid_from:
            continue
        if schedule.valid_until is not None and local_date > schedule.valid_until:
            continue
        if local_start.time().replace(tzinfo=None) < schedule.local_start:
            continue
        if local_end.time().replace(tzinfo=None) > schedule.local_end:
            continue

        start_roundtrip = resolve_local_instant(
            local_start.replace(tzinfo=None),
            schedule.timezone,
        )
        end_roundtrip = resolve_local_instant(
            local_end.replace(tzinfo=None),
            schedule.timezone,
        )
        if start_roundtrip == start and end_roundtrip == end:
            return True

    return False


def _recurring_candidates(
    schedule: RecurringAvailability,
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    step: timedelta,
) -> set[AvailableInterval]:
    try:
        zone = ZoneInfo(schedule.timezone)
    except ZoneInfoNotFoundError as exc:
        local_value = window_start.replace(tzinfo=None)
        raise LocalTimeResolutionError(
            schedule.timezone,
            local_value,
            "in an unknown timezone",
        ) from exc

    first_date = window_start.astimezone(zone).date()
    last_date = window_end.astimezone(zone).date()
    current_date = first_date
    candidates: set[AvailableInterval] = set()

    while current_date <= last_date:
        if _schedule_applies_on(schedule, current_date):
            local_cursor = datetime.combine(current_date, schedule.local_start)
            local_close = datetime.combine(current_date, schedule.local_end)
            while local_cursor + duration <= local_close:
                local_end = local_cursor + duration
                start_at = resolve_local_instant(local_cursor, schedule.timezone)
                end_at = resolve_local_instant(local_end, schedule.timezone)
                if end_at > start_at and start_at >= window_start and end_at <= window_end:
                    candidates.add(AvailableInterval(start_at, end_at))
                local_cursor += step
        current_date += timedelta(days=1)

    return candidates


def _explicit_available_candidates(
    exception: AvailabilityException,
    *,
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    step: timedelta,
) -> set[AvailableInterval]:
    start = require_aware_utc(exception.start_at, "exception.start_at")
    end = require_aware_utc(exception.end_at, "exception.end_at")
    cursor = start
    candidates: set[AvailableInterval] = set()
    while cursor + duration <= end:
        candidate = AvailableInterval(cursor, cursor + duration)
        if candidate.start_at >= window_start and candidate.end_at <= window_end:
            candidates.add(candidate)
        cursor += step
    return candidates


def _schedule_applies_on(schedule: RecurringAvailability, value: date) -> bool:
    if value.weekday() != schedule.weekday:
        return False
    if schedule.valid_from is not None and value < schedule.valid_from:
        return False
    return schedule.valid_until is None or value <= schedule.valid_until


def _blocked_by_unavailable_exception(
    exceptions: tuple[AvailabilityException, ...],
    interval: AvailableInterval,
) -> bool:
    return any(
        exception.kind is ExceptionKind.UNAVAILABLE
        and _overlaps(
            interval.start_at,
            interval.end_at,
            exception.start_at,
            exception.end_at,
        )
        for exception in exceptions
    )


def _has_capacity(
    profile: ResourceAvailability,
    interval: AvailableInterval,
    required_quantity: int,
) -> bool:
    overlapping = [
        claim
        for claim in profile.live_claims
        if _overlaps(
            interval.start_at,
            interval.end_at,
            claim.start_at,
            claim.end_at,
        )
    ]
    if profile.capacity_model is CapacityModel.EXCLUSIVE:
        return required_quantity == 1 and not overlapping
    used = sum(claim.quantity for claim in overlapping)
    return used + required_quantity <= profile.capacity_units


def _overlaps(
    left_start: datetime,
    left_end: datetime,
    right_start: datetime,
    right_end: datetime,
) -> bool:
    return left_start < right_end and right_start < left_end
