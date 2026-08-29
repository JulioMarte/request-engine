from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from .operational_support import PgConnection

TZ = ZoneInfo("America/Santo_Domingo")
_LATE_ANCHOR = time(22, 0)


def anchor_for(now: datetime) -> datetime:
    """Absolute search-window start for slot-based test worlds.

    Slot worlds seed one full 00:00-23:59 business day in the repository
    default timezone (America/Santo_Domingo) and book consecutive 5-minute
    slots from this instant. Near the end of that local day the remaining
    runway cannot fit the world, so the whole world anchors to the next local
    day at 00:05 instead of straddling midnight.
    """

    local = now.astimezone(TZ)
    if local.time() >= _LATE_ANCHOR:
        return datetime.combine(local.date() + timedelta(days=1), time(0, 5), tzinfo=TZ)
    return local + timedelta(minutes=5)


def world_window_start(conn: PgConnection) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return anchor_for(cast(datetime, row[0]))


def world_weekday(conn: PgConnection) -> int:
    return world_window_start(conn).weekday()
