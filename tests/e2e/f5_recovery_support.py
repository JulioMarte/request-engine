from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID, uuid4

from httpx import AsyncClient

from request_engine.platform.security.context import ActorContext

from .f4_capacity_support import f4_actor, same_day_slots
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth
from .world_clock import location_timezone, world_weekday

_F5_CAPABILITIES = frozenset(
    {
        "operational_recovery.propose",
        "operational_recovery.read",
        "operational_recovery.execute",
        "operational_recovery.configure_autonomy",
    }
)


def f5_actor(sandbox: TenantSandbox) -> ActorContext:
    base = f4_actor(sandbox)
    return ActorContext(
        base.organization_id, base.principal_id, base.capabilities | _F5_CAPABILITIES
    )


async def book_commitments(
    client: AsyncClient,
    conn: PgConnection,
    sandbox: TenantSandbox,
    *,
    count: int = 10,
) -> tuple[list[UUID], list[dict[str, Any]]]:
    slots = await same_day_slots(client, conn, sandbox)
    assert len(slots) >= count + 1, (
        f"test world slot supply exhausted: found {len(slots)}, need {count + 1}; the world"
        " business day is configured in locations.timezone and needs hours of runway"
    )
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


def _assignment_id_at(
    conn: PgConnection,
    sandbox: TenantSandbox,
    instant: datetime,
) -> UUID:
    row = conn.execute(
        """
        SELECT id
        FROM request_engine.resource_location_assignments
        WHERE organization_id = %s
          AND resource_id = %s
          AND location_id = %s
          AND status = 'active'
          AND effective_during @> %s::timestamptz
        ORDER BY lower(effective_during) DESC
        LIMIT 1
        """,
        (sandbox.organization_id, sandbox.resource_id, sandbox.location_id, instant),
    ).fetchone()
    assert row is not None, "recovery source has no active contextual assignment"
    return cast(UUID, row[0])


def restrict_source_to_first_slots(
    conn: PgConnection,
    sandbox: TenantSandbox,
    slots: list[dict[str, Any]],
    *,
    count: int,
) -> None:
    if count <= 0 or count > len(slots):
        raise ValueError("count must select at least one available slot")
    start_at = datetime.fromisoformat(cast(str, slots[0]["start_at"])).astimezone(
        location_timezone(conn, sandbox)
    )
    end_at = datetime.fromisoformat(cast(str, slots[count - 1]["end_at"])).astimezone(
        location_timezone(conn, sandbox)
    )
    assert start_at.date() == end_at.date(), "slot world crossed local midnight"
    weekday = start_at.weekday()
    assignment_id = _assignment_id_at(conn, sandbox, start_at)
    conn.execute(
        """
        DELETE FROM request_engine.resource_location_availability
        WHERE organization_id = %s
          AND resource_location_assignment_id = %s
          AND weekday = %s
        """,
        (sandbox.organization_id, assignment_id, weekday),
    )
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id,
            resource_location_assignment_id,
            weekday,
            local_start,
            local_end
        ) VALUES (%s, %s, %s, %s, %s)
        """,
        (
            sandbox.organization_id,
            assignment_id,
            weekday,
            start_at.timetz().replace(tzinfo=None),
            end_at.timetz().replace(tzinfo=None),
        ),
    )


def restrict_source_to_first_six(
    conn: PgConnection,
    sandbox: TenantSandbox,
    slots: list[dict[str, Any]],
) -> None:
    restrict_source_to_first_slots(conn, sandbox, slots, count=6)


def seed_replacement_resource(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "SELECT capability_id FROM request_engine.offering_resource_requirements "
        "WHERE organization_id=%s AND id=%s",
        (sandbox.organization_id, sandbox.requirement_id),
    ).fetchone()
    assert row is not None
    resource = conn.execute(
        """
        INSERT INTO request_engine.resources (
            organization_id, resource_key, display_name, capacity_model, capacity_units
        ) VALUES (%s, %s, %s, 'exclusive', 1)
        RETURNING id
        """,
        (sandbox.organization_id, f"recovery-{uuid4().hex}", "Recovery resource"),
    ).fetchone()
    assert resource is not None
    resource_id = cast(UUID, resource[0])
    conn.execute(
        "INSERT INTO request_engine.resource_capability_assignments "
        "(organization_id,resource_id,capability_id) VALUES (%s,%s,%s)",
        (sandbox.organization_id, resource_id, row[0]),
    )
    assignment = conn.execute(
        """
        INSERT INTO request_engine.resource_location_assignments (
            organization_id, resource_id, location_id, effective_during
        ) VALUES (
            %s, %s, %s,
            tstzrange('2000-01-01T00:00:00+00'::timestamptz, NULL, '[)')
        )
        RETURNING id
        """,
        (sandbox.organization_id, resource_id, sandbox.location_id),
    ).fetchone()
    assert assignment is not None
    weekday = world_weekday(conn, sandbox)
    conn.execute(
        """
        INSERT INTO request_engine.resource_location_availability (
            organization_id,
            resource_location_assignment_id,
            weekday,
            local_start,
            local_end
        ) VALUES (%s, %s, %s, '00:00', '23:59')
        """,
        (sandbox.organization_id, assignment[0], weekday),
    )
    return resource_id
