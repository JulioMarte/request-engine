from datetime import timedelta
from typing import Any, cast

from httpx import AsyncClient

from request_engine.platform.security.context import ActorContext

from .f3_acceptance_assertions import acceptance_actor
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth

_F4_CAPABILITIES = frozenset(
    {
        "live_capacity.read",
        "live_capacity.customer_read",
        "live_capacity.evaluate_intake",
        "live_capacity.configure_scope",
        "live_capacity.configure_estimate",
    }
)


def f4_actor(sandbox: TenantSandbox) -> ActorContext:
    base = acceptance_actor(sandbox)
    return ActorContext(
        organization_id=base.organization_id,
        principal_id=base.principal_id,
        capabilities=base.capabilities | _F4_CAPABILITIES,
    )


def seed_today_schedule(conn: PgConnection, sandbox: TenantSandbox) -> None:
    row = conn.execute(
        "SELECT extract(isodow FROM clock_timestamp() "
        "AT TIME ZONE 'America/Santo_Domingo')::int - 1"
    ).fetchone()
    assert row is not None
    weekday = row[0]
    conn.execute(
        "DELETE FROM request_engine.availability_schedules "
        "WHERE organization_id=%s AND resource_id=%s AND weekday=%s",
        (sandbox.organization_id, sandbox.resource_id, weekday),
    )
    conn.execute(
        "INSERT INTO request_engine.availability_schedules "
        "(organization_id,resource_id,weekday,local_start,local_end,timezone) "
        "VALUES (%s,%s,%s,'00:00','23:59','America/Santo_Domingo')",
        (sandbox.organization_id, sandbox.resource_id, weekday),
    )


async def same_day_slots(
    client: AsyncClient,
    conn: PgConnection,
    sandbox: TenantSandbox,
) -> list[dict[str, Any]]:
    row = conn.execute("SELECT clock_timestamp()").fetchone()
    assert row is not None
    starts_at = row[0] + timedelta(minutes=5)
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": starts_at.isoformat(),
            "window_end": (starts_at + timedelta(hours=6)).isoformat(),
        },
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    slots = cast(list[dict[str, Any]], response.json())
    assert len(slots) >= 2
    return slots
