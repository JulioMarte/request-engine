from datetime import timedelta
from typing import Any, cast

from httpx import AsyncClient

from request_engine.platform.security.context import ActorContext

from .f3_acceptance_assertions import acceptance_actor
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth
from .world_clock import world_weekday, world_window_start

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


def seed_live_execution_assignment(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2026-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        """,
        (sandbox.organization_id, sandbox.resource_id, sandbox.location_id),
    )


def seed_today_schedule(conn: PgConnection, sandbox: TenantSandbox) -> None:
    weekday = world_weekday(conn)
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
    starts_at = world_window_start(conn)
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
    assert len(slots) >= 2, (
        "test world slot supply exhausted; slot worlds seed one 00:00-23:59 "
        "business day in America/Santo_Domingo (the repository default timezone) "
        "and anchor to the next local day after 22:00 local"
    )
    return slots
