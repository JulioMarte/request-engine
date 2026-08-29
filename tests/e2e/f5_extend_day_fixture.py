from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from zoneinfo import ZoneInfo

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox

_TZ = ZoneInfo("America/Santo_Domingo")


def grant_extend_day_authority(conn: PgConnection, sandbox: TenantSandbox) -> None:
    for scope in ("operations.manage_profile", "operations.manage_supply"):
        conn.execute(
            "INSERT INTO request_engine.representations "
            "(organization_id,principal_id,represented_party_id,authority_kind,"
            "scope_key,valid_until) "
            "VALUES (%s,%s,%s,'delegated',%s,clock_timestamp() + interval '1 day')",
            (sandbox.organization_id, sandbox.principal_id, sandbox.party_id, scope),
        )


def close_location_after_slots(
    conn: PgConnection,
    sandbox: TenantSandbox,
    slots: list[dict[str, Any]],
    *,
    count: int,
) -> None:
    start = datetime.fromisoformat(cast(str, slots[0]["start_at"])).astimezone(_TZ)
    end = datetime.fromisoformat(cast(str, slots[count - 1]["end_at"])).astimezone(_TZ)
    conn.execute(
        "DELETE FROM request_engine.location_operational_hours "
        "WHERE organization_id=%s AND location_id=%s AND weekday=%s",
        (sandbox.organization_id, sandbox.location_id, start.weekday()),
    )
    conn.execute(
        "INSERT INTO request_engine.location_operational_hours "
        "(organization_id,location_id,weekday,local_start,local_end) "
        "VALUES (%s,%s,%s,%s,%s)",
        (
            sandbox.organization_id,
            sandbox.location_id,
            start.weekday(),
            start.timetz().replace(tzinfo=None),
            end.timetz().replace(tzinfo=None),
        ),
    )


def recurring_schedule_snapshot(
    conn: PgConnection,
    sandbox: TenantSandbox,
    assignment_id: object,
) -> tuple[list[tuple[object, ...]], list[tuple[object, ...]]]:
    location_rows = conn.execute(
        "SELECT weekday,local_start,local_end FROM request_engine.location_operational_hours "
        "WHERE organization_id=%s AND location_id=%s ORDER BY weekday,local_start",
        (sandbox.organization_id, sandbox.location_id),
    ).fetchall()
    assignment_rows = conn.execute(
        "SELECT weekday,local_start,local_end "
        "FROM request_engine.resource_location_availability "
        "WHERE organization_id=%s AND resource_location_assignment_id=%s "
        "ORDER BY weekday,local_start",
        (sandbox.organization_id, assignment_id),
    ).fetchall()
    return ([tuple(row) for row in location_rows], [tuple(row) for row in assignment_rows])
