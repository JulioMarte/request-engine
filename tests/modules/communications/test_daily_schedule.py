from datetime import UTC, datetime, time

import pytest

from request_engine.modules.communications.domain.daily_schedule import (
    ReminderScheduleError,
    next_daily_occurrence,
    normalize_daily_times,
)


def test_daily_times_are_normalized_sorted_and_unique() -> None:
    normalized = normalize_daily_times((time(20, 0), time(8, 0)))
    assert normalized == (time(8, 0), time(20, 0))

    with pytest.raises(ReminderScheduleError, match="unique"):
        normalize_daily_times((time(8, 0), time(8, 0)))


def test_next_occurrence_uses_local_timezone() -> None:
    occurrence = next_daily_occurrence(
        after=datetime(2026, 8, 17, 11, 0, tzinfo=UTC),
        timezone="America/Santo_Domingo",
        times=(time(8, 0), time(20, 0)),
    )
    assert occurrence == datetime(2026, 8, 17, 12, 0, tzinfo=UTC)


def test_nonexistent_dst_time_is_skipped_for_that_date() -> None:
    occurrence = next_daily_occurrence(
        after=datetime(2026, 3, 8, 6, 0, tzinfo=UTC),
        timezone="America/New_York",
        times=(time(2, 30),),
    )
    assert occurrence == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def test_ambiguous_dst_time_emits_once_at_first_chronological_instant() -> None:
    occurrence = next_daily_occurrence(
        after=datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
        timezone="America/New_York",
        times=(time(1, 30),),
    )
    assert occurrence == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)

    next_occurrence = next_daily_occurrence(
        after=occurrence,
        timezone="America/New_York",
        times=(time(1, 30),),
    )
    assert next_occurrence == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
