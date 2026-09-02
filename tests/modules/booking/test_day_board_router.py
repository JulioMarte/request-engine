from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException, status

from request_engine.modules.booking.api.day_board_routes import validate_day_board_window

_NOW = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)


def test_day_board_window_requires_timezone_offsets() -> None:
    naive = _NOW.replace(tzinfo=None)

    with pytest.raises(HTTPException) as raised:
        validate_day_board_window(naive, naive + timedelta(hours=1))

    assert raised.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.parametrize(
    ("window_start", "window_end"),
    [
        (_NOW, _NOW),
        (_NOW, _NOW - timedelta(minutes=1)),
        (_NOW, _NOW + timedelta(hours=48, seconds=1)),
    ],
)
def test_day_board_window_rejects_invalid_bounds(
    window_start: datetime, window_end: datetime
) -> None:
    with pytest.raises(HTTPException) as raised:
        validate_day_board_window(window_start, window_end)

    assert raised.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_day_board_window_accepts_bounded_offset_aware_range() -> None:
    validate_day_board_window(_NOW, _NOW + timedelta(hours=48))
