from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class ReminderScheduleError(ValueError):
    pass


def normalize_daily_times(values: tuple[time, ...]) -> tuple[time, ...]:
    if not values:
        raise ReminderScheduleError("daily reminder schedule requires at least one time")
    normalized: list[time] = []
    for value in values:
        if value.tzinfo is not None:
            raise ReminderScheduleError(
                "daily reminder times must be naive local wall-clock values"
            )
        normalized.append(value.replace(microsecond=0))
    unique = tuple(sorted(set(normalized)))
    if len(unique) != len(values):
        raise ReminderScheduleError("daily reminder times must be unique")
    return unique


def next_daily_occurrence(
    *,
    after: datetime,
    timezone: str,
    times: tuple[time, ...],
) -> datetime:
    """Return the next wall-clock daily occurrence strictly after `after`.

    DST semantics are deterministic for reminders: nonexistent local instants are
    skipped for that date; ambiguous instants use the first chronological UTC
    occurrence so a daily reminder is emitted once, not twice.
    """

    if after.tzinfo is None or after.utcoffset() is None:
        raise ReminderScheduleError("after must be timezone-aware")
    normalized = normalize_daily_times(times)
    try:
        zone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ReminderScheduleError(f"unknown IANA timezone: {timezone}") from exc

    after_utc = after.astimezone(UTC)
    local_date = after_utc.astimezone(zone).date()
    for offset in range(0, 370):
        candidate_date = local_date + timedelta(days=offset)
        for local_time in normalized:
            candidates = _resolve_local_candidates(candidate_date, local_time, zone)
            if not candidates:
                continue
            candidate = candidates[0]
            if candidate > after_utc:
                return candidate
    raise ReminderScheduleError("could not resolve a reminder occurrence within one year")


def _resolve_local_candidates(
    value_date: date,
    value_time: time,
    zone: ZoneInfo,
) -> tuple[datetime, ...]:
    local_value = datetime.combine(value_date, value_time)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        aware = local_value.replace(tzinfo=zone, fold=fold)
        utc_value = aware.astimezone(UTC)
        roundtrip = utc_value.astimezone(zone).replace(tzinfo=None)
        if roundtrip == local_value:
            candidates.add(utc_value)
    return tuple(sorted(candidates))
