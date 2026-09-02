from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.day_board import ReservationDayBoardEntry

MAX_DAY_BOARD_WINDOW = timedelta(hours=36)


class ReservationDayBoardReader(Protocol):
    async def read_window(
        self,
        organization_id: UUID,
        *,
        window_start: datetime,
        window_end: datetime,
    ) -> tuple[ReservationDayBoardEntry, ...]: ...


def validate_day_board_window(window_start: datetime, window_end: datetime) -> None:
    if window_start.utcoffset() is None or window_end.utcoffset() is None:
        raise ValueError("day-board window timestamps must include a timezone offset")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    if window_end - window_start > MAX_DAY_BOARD_WINDOW:
        raise ValueError("day-board window cannot exceed 36 hours")
