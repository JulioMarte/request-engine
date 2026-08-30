from __future__ import annotations

from datetime import datetime, timedelta
from typing import cast
from zoneinfo import ZoneInfo

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox

DEFAULT_BUSINESS_TIMEZONE = "America/Santo_Domingo"
_CANDIDATES = (
    DEFAULT_BUSINESS_TIMEZONE,
    "Asia/Tokyo",
    "Pacific/Auckland",
)
_RUNWAY_START = datetime.min.time().replace(hour=0, minute=30)
_RUNWAY_END = datetime.min.time().replace(hour=21, minute=30)


def pick_business_timezone(now_utc: datetime) -> str:
    """Choose the business timezone whose local day still has runway for the world.

    Slot worlds book a full business day of 5-minute commitments, so the
    configured business day must have hours left before its local midnight.
    Production keeps this choice in ``locations.timezone``; the world writes the
    picked value there through ``configure_world_timezone``.
    """

    for candidate in _CANDIDATES:
        local = now_utc.astimezone(ZoneInfo(candidate)).timetz().replace(tzinfo=None)
        if _RUNWAY_START <= local <= _RUNWAY_END:
            return candidate
    return _CANDIDATES[-1]


def configure_world_timezone(conn: PgConnection, sandbox: TenantSandbox) -> str:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    timezone = pick_business_timezone(cast(datetime, row[0]))
    conn.execute(
        "UPDATE request_engine.locations SET timezone=%s WHERE organization_id=%s AND id=%s",
        (timezone, sandbox.organization_id, sandbox.location_id),
    )
    return timezone


def location_timezone(conn: PgConnection, sandbox: TenantSandbox) -> ZoneInfo:
    row = conn.execute(
        "SELECT timezone FROM request_engine.locations WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.location_id),
    ).fetchone()
    assert row is not None
    return ZoneInfo(cast(str, row[0]))


def world_window_start(conn: PgConnection) -> datetime:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    return cast(datetime, row[0]) + timedelta(minutes=5)


def world_weekday(conn: PgConnection, sandbox: TenantSandbox) -> int:
    local_start = world_window_start(conn).astimezone(location_timezone(conn, sandbox))
    return local_start.weekday()
