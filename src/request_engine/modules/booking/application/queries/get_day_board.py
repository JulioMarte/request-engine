from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from uuid import UUID

from request_engine.modules.booking.contracts.day_board import DayBoardEntry

_MAX_WINDOW = timedelta(hours=48)


@dataclass(frozen=True, slots=True)
class GetDayBoardQuery:
    organization_id: UUID
    window_start: datetime
    window_end: datetime
    location_id: UUID | None = None
    limit: int = 500


class DayBoardReader(Protocol):
    async def get_day_board(self, query: GetDayBoardQuery) -> tuple[DayBoardEntry, ...]: ...


async def get_day_board(
    reader: DayBoardReader, query: GetDayBoardQuery
) -> tuple[DayBoardEntry, ...]:
    if query.window_end <= query.window_start:
        raise ValueError("day board window_end must be after window_start")
    if query.window_end - query.window_start > _MAX_WINDOW:
        raise ValueError("day board window may not exceed 48 hours")
    if not 1 <= query.limit <= 500:
        raise ValueError("day board limit must be between 1 and 500")
    return await reader.get_day_board(query)
