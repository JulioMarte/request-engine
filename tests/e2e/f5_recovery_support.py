from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from httpx import AsyncClient

from request_engine.platform.security.context import ActorContext

from .f4_capacity_support import f4_actor, same_day_slots
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth

_F5_CAPABILITIES = frozenset(
    {
        "operational_recovery.propose",
        "operational_recovery.read",
        "operational_recovery.execute",
    }
)
_TZ = ZoneInfo("America/Santo_Domingo")


def f5_actor(sandbox: TenantSandbox) -> ActorContext:
    base = f4_actor(sandbox)
    return ActorContext(
        organization_id=base.organization_id,
        principal_id=base.principal_id,
        capabilities=base.capabilities | _F5_CAPABILITIES,
    )


async def book_commitments(
    client: AsyncClient,
    conn: PgConnection,
    sandbox: TenantSandbox,
    *,
    count: int = 10,
) -> tuple[list[UUID], list[dict[str, Any]]]:
    slots = await same_day_slots(client, conn, sandbox)
    assert len(slots) >= count + 1
    reservations: list[UUID] = []
    for slot in slots[:count]:
        response = await client.post(
            "/v1/appointments",
            json={
                "option_id": str(slot["option_id"]),
                "subject_party_id": str(sandbox.party_id),
            },
            headers=auth(sandbox, idempotency_key=f"f5-book-{uuid4().hex}"),
        )
        assert response.status_code == 201, response.text
        reservations.append(UUID(response.json()["id"]))
    return reservations, slots


def restrict_source_to_first_six(
    conn: PgConnection,
    sandbox: TenantSandbox,
    slots: list[dict[str, Any]],
) -> None:
    start_at = datetime.fromisoformat(cast(str, slots[0]["start_at"])).astimezone(_TZ)
    end_at = datetime.fromisoformat(cast(str, slots[5]["end_at"])).astimezone(_TZ)
    assert start_at.date() == end_at.date()
    weekday = start_at.weekday()
    conn.execute(
        "DELETE FROM request_engine.availability_schedules "
        "WHERE organization_id=%s AND resource_id=%s AND weekday=%s",
        (sandbox.organization_id, sandbox.resource_id, weekday),
    )
    conn.execute(
        "INSERT INTO request_engine.availability_schedules "
        "(organization_id,resource_id,weekday,local_start,local_end,timezone) "
        "VALUES (%s,%s,%s,%s,%s,'America/Santo_Domingo')",
        (
            sandbox.organization_id,
            sandbox.resource_id,
            weekday,
            start_at.timetz().replace(tzinfo=None),
            end_at.timetz().replace(tzinfo=None),
        ),
    )


def seed_replacement_resource(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "SELECT capability_id FROM request_engine.offering_resource_requirements "
        "WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.requirement_id),
    ).fetchone()
    assert row is not None
    resource = conn.execute(
        "INSERT INTO request_engine.resources "
        "(organization_id,location_id,resource_key,display_name,capacity_model,capacity_units) "
        "VALUES (%s,%s,%s,%s,'exclusive',1) RETURNING id",
        (
            sandbox.organization_id,
            sandbox.location_id,
            f"recovery-{uuid4().hex}",
            "Recovery resource",
        ),
    ).fetchone()
    assert resource is not None
    resource_id = cast(UUID, resource[0])
    conn.execute(
        "INSERT INTO request_engine.resource_capability_assignments "
        "(organization_id,resource_id,capability_id) VALUES (%s,%s,%s)",
        (sandbox.organization_id, resource_id, row[0]),
    )
    weekday = datetime.now(_TZ).weekday()
    conn.execute(
        "INSERT INTO request_engine.availability_schedules "
        "(organization_id,resource_id,weekday,local_start,local_end,timezone) "
        "VALUES (%s,%s,%s,'00:00','23:59','America/Santo_Domingo')",
        (sandbox.organization_id, resource_id, weekday),
    )
    return resource_id
