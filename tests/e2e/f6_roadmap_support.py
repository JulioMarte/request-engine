from datetime import date, time

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox
from .world_clock import world_weekday


def seed_location_operational_hours(
    conn: PgConnection,
    sandbox: TenantSandbox,
    *,
    local_start: time = time(0, 30),
    local_end: time = time(23, 30),
    valid_from: date | None = None,
    valid_until: date | None = None,
    active: bool = True,
) -> None:
    conn.execute(
        "INSERT INTO request_engine.location_operational_hours "
        "(organization_id,location_id,weekday,local_start,local_end,valid_from,valid_until,active) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            sandbox.organization_id,
            sandbox.location_id,
            world_weekday(conn, sandbox),
            local_start,
            local_end,
            valid_from,
            valid_until,
            active,
        ),
    )
