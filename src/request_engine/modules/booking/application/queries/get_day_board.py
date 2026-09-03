from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.day_board import ReservationDayBoardEntry

MAX_DAY_BOARD_WINDOW = timedelta(hours=36)
MIN_DAY_BOARD_LIMIT = 1
MAX_DAY_BOARD_LIMIT = 500


class ReservationDayBoardReader(Protocol):
    async def read_window(
        self,
        organization_id: UUID,
        *,
        window_start: datetime,
        window_end: datetime,
        location_id: UUID | None = None,
        limit: int = 500,
    ) -> tuple[ReservationDayBoardEntry, ...]: ...


def validate_day_board_window(window_start: datetime, window_end: datetime) -> None:
    if window_start.utcoffset() is None or window_end.utcoffset() is None:
        raise ValueError("day-board window timestamps must include a timezone offset")
    if window_end <= window_start:
        raise ValueError("window_end must be after window_start")
    if window_end - window_start > MAX_DAY_BOARD_WINDOW:
        raise ValueError("day-board window cannot exceed 36 hours")


def validate_day_board_limit(limit: int) -> None:
    if not MIN_DAY_BOARD_LIMIT <= limit <= MAX_DAY_BOARD_LIMIT:
        raise ValueError("day-board limit must be between 1 and 500")
