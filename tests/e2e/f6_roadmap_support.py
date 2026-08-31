from datetime import date, time
from typing import cast

from .discovery_operational_support import grant_manage_discovery
from .discovery_seed_support import create_classification
from .f4_capacity_support import seed_live_execution_assignment, seed_today_schedule
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox
from .world_clock import world_weekday


def local_noon_timezone(conn: PgConnection) -> str:
    row = conn.execute(
        "SELECT EXTRACT(HOUR FROM clock_timestamp() AT TIME ZONE 'UTC')::int"
    ).fetchone()
    assert row is not None
    offset = 12 - cast(int, row[0])
    if offset > 12:
        offset -= 24
    if offset < -12:
        offset += 24
    if offset == 0:
        return "UTC"
    sign = "-" if offset > 0 else "+"
    return f"Etc/GMT{sign}{abs(offset)}"


def seed_named_resource_day_schedule(
    conn: PgConnection,
    sandbox: TenantSandbox,
    *,
    display_name: str,
) -> None:
    conn.execute(
        "UPDATE request_engine.resources SET display_name=%s WHERE organization_id=%s AND id=%s",
        (display_name, sandbox.organization_id, sandbox.resource_id),
    )
    seed_today_schedule(conn, sandbox, business_timezone=local_noon_timezone(conn))


def seed_publishable_discovery_world(conn: PgConnection, sandbox: TenantSandbox) -> None:
    seed_live_execution_assignment(conn, sandbox)
    grant_manage_discovery(conn, sandbox)
    classification_id, _ = create_classification(conn)
    conn.execute(
        "INSERT INTO request_engine.offering_service_classifications "
        "(organization_id, offering_id, service_classification_id) VALUES (%s, %s, %s)",
        (sandbox.organization_id, sandbox.offering_id, classification_id),
    )


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
