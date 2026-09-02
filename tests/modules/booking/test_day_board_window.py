from datetime import datetime, timedelta, timezone

import pytest

from request_engine.modules.booking.application.queries.get_day_board import (
    validate_day_board_window,
)


def test_day_board_accepts_bounded_timezone_aware_window() -> None:
    start = datetime(2030, 1, 7, 4, 0, tzinfo=timezone(timedelta(hours=-4)))
    validate_day_board_window(start, start + timedelta(days=1))


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (datetime(2030, 1, 7, 4), datetime(2030, 1, 8, 4)),
        (
            datetime(2030, 1, 8, tzinfo=timezone.utc),
            datetime(2030, 1, 7, tzinfo=timezone.utc),
        ),
        (
            datetime(2030, 1, 7, tzinfo=timezone.utc),
            datetime(2030, 1, 9, tzinfo=timezone.utc),
        ),
    ],
)
def test_day_board_rejects_ambiguous_or_unbounded_windows(
    start: datetime,
    end: datetime,
) -> None:
    with pytest.raises(ValueError):
        validate_day_board_window(start, end)
