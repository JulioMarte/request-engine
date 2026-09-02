from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from request_engine.modules.booking.application.queries.get_day_board import (
    GetDayBoardQuery,
    get_day_board,
)

_NOW = datetime(2030, 1, 7, 8, 0, tzinfo=UTC)


class _Reader:
    def __init__(self) -> None:
        self.queries: list[GetDayBoardQuery] = []

    async def get_day_board(self, query: GetDayBoardQuery) -> tuple[()]:
        self.queries.append(query)
        return ()


def _query(**overrides: object) -> GetDayBoardQuery:
    values: dict[str, object] = {
        "organization_id": uuid4(),
        "window_start": _NOW,
        "window_end": _NOW + timedelta(hours=12),
        "limit": 100,
    }
    values.update(overrides)
    return GetDayBoardQuery(**values)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_valid_day_board_query_delegates_without_rewriting_window() -> None:
    reader = _Reader()
    query = _query(location_id=uuid4())

    result = await get_day_board(reader, query)

    assert result == ()
    assert reader.queries == [query]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "query",
    [
        _query(window_end=_NOW),
        _query(window_end=_NOW - timedelta(minutes=1)),
        _query(window_end=_NOW + timedelta(hours=48, seconds=1)),
        _query(limit=0),
        _query(limit=501),
    ],
)
async def test_invalid_day_board_query_is_rejected_before_reader(query: GetDayBoardQuery) -> None:
    reader = _Reader()

    with pytest.raises(ValueError):
        await get_day_board(reader, query)

    assert reader.queries == []
