from datetime import UTC, date, datetime, time

import pytest

from request_engine.modules.booking.domain.availability import (
    AvailabilityException,
    CapacityModel,
    ExceptionKind,
    LocalTimeResolutionError,
    RecurringAvailability,
    ResourceAvailability,
    find_resource_intervals,
    resolve_local_instant,
)


def _profile(*, exceptions: tuple[AvailabilityException, ...] = ()) -> ResourceAvailability:
    return ResourceAvailability(
        capacity_model=CapacityModel.EXCLUSIVE,
        capacity_units=1,
        default_timezone="America/Santo_Domingo",
        schedules=(
            RecurringAvailability(
                weekday=0,
                local_start=time(9, 0),
                local_end=time(11, 0),
                timezone="America/Santo_Domingo",
                valid_from=None,
                valid_until=None,
            ),
        ),
        exceptions=exceptions,
        live_claims=(),
    )


def test_recurring_schedule_generates_half_hour_slots_in_utc() -> None:
    slots = find_resource_intervals(
        _profile(),
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        duration_minutes=30,
        step_minutes=30,
        required_quantity=1,
    )

    assert [(slot.start_at.hour, slot.start_at.minute) for slot in slots] == [
        (13, 0),
        (13, 30),
        (14, 0),
        (14, 30),
    ]


def test_unavailable_exception_wins_over_recurring_schedule() -> None:
    blocked = AvailabilityException(
        start_at=datetime(2026, 8, 17, 13, 30, tzinfo=UTC),
        end_at=datetime(2026, 8, 17, 14, 0, tzinfo=UTC),
        kind=ExceptionKind.UNAVAILABLE,
    )
    slots = find_resource_intervals(
        _profile(exceptions=(blocked,)),
        window_start=datetime(2026, 8, 17, 13, 0, tzinfo=UTC),
        window_end=datetime(2026, 8, 17, 15, 0, tzinfo=UTC),
        duration_minutes=30,
        step_minutes=30,
        required_quantity=1,
    )

    assert all(slot.start_at != blocked.start_at for slot in slots)


def test_nonexistent_dst_local_time_is_rejected() -> None:
    with pytest.raises(LocalTimeResolutionError, match="nonexistent"):
        resolve_local_instant(
            datetime.combine(date(2026, 3, 8), time(2, 30)),
            "America/New_York",
        )


def test_ambiguous_dst_local_time_is_rejected() -> None:
    with pytest.raises(LocalTimeResolutionError, match="ambiguous"):
        resolve_local_instant(
            datetime.combine(date(2026, 11, 1), time(1, 30)),
            "America/New_York",
        )
