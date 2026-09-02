from uuid import uuid4

import pytest

from request_engine.platform.db.session import SessionFactory

from .f5_booking_fixture import five_minute_sandbox
from .f5_contextual_support import contextualize_recovery_supply
from .f6_copilot_support import copilot_actor
from .operational_support import PgConnection
from .tenant_sandbox import auth, client_with_actors, seed_tenant_sandbox

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.e2e,
    pytest.mark.postgres,
    pytest.mark.contract,
    pytest.mark.adversarial,
]


def _resource_name(conn: PgConnection, object_id: object) -> str:
    row = conn.execute(
        "SELECT display_name FROM request_engine.resources WHERE id=%s",
        (object_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


def _offering_name(conn: PgConnection, object_id: object) -> str:
    row = conn.execute(
        "SELECT display_name FROM request_engine.offerings WHERE id=%s",
        (object_id,),
    ).fetchone()
    assert row is not None
    return str(row[0])


async def test_f6_lookup_tools_never_surface_foreign_tenant_entities(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    local = seed_tenant_sandbox(e2e_admin_conn, "f6-opacity-local")
    foreign = seed_tenant_sandbox(e2e_admin_conn, "f6-opacity-foreign")
    actors = {local.token: copilot_actor(local)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        resources = await client.get(
            "/v1/operational-copilot/tools/resources",
            params={"reference": _resource_name(e2e_admin_conn, foreign.resource_id)},
            headers=auth(local),
        )
        offerings = await client.get(
            "/v1/operational-copilot/tools/offerings",
            params={"reference": _offering_name(e2e_admin_conn, foreign.offering_id)},
            headers=auth(local),
        )
        queues = await client.get(
            "/v1/operational-copilot/tools/queues",
            headers=auth(local),
        )
    assert resources.status_code == 200 and resources.json() == []
    assert offerings.status_code == 200 and offerings.json() == []
    assert queues.status_code == 200
    assert str(foreign.queue_id) not in {row["service_queue_id"] for row in queues.json()}


async def test_f6_foreign_and_random_state_ids_are_equally_opaque(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    local = five_minute_sandbox(
        e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, "f6-opacity-state-local")
    )
    foreign = five_minute_sandbox(
        e2e_admin_conn, seed_tenant_sandbox(e2e_admin_conn, "f6-opacity-state-foreign")
    )
    foreign_supply = contextualize_recovery_supply(e2e_admin_conn, foreign)
    random_id = uuid4()
    actors = {local.token: copilot_actor(local)}
    async with client_with_actors(e2e_session_factory, actors) as client:
        foreign_clock = await client.get(
            f"/v1/operational-copilot/tools/locations/{foreign.location_id}/clock",
            headers=auth(local),
        )
        random_clock = await client.get(
            f"/v1/operational-copilot/tools/locations/{random_id}/clock",
            headers=auth(local),
        )
        foreign_day = await client.get(
            f"/v1/operational-copilot/tools/assignments/{foreign_supply.assignment_id}/day-end",
            params={"weekday": 0},
            headers=auth(local),
        )
        random_day = await client.get(
            f"/v1/operational-copilot/tools/assignments/{random_id}/day-end",
            params={"weekday": 0},
            headers=auth(local),
        )
        foreign_intake = await client.get(
            f"/v1/operational-copilot/tools/queues/{foreign.queue_id}/intake",
            headers=auth(local),
        )
        random_intake = await client.get(
            f"/v1/operational-copilot/tools/queues/{random_id}/intake",
            headers=auth(local),
        )
    assert foreign_clock.status_code == random_clock.status_code == 404
    assert foreign_clock.json() == random_clock.json()
    assert foreign_day.status_code == random_day.status_code == 200
    assert foreign_day.json()["day_end"] is None and random_day.json()["day_end"] is None
    assert foreign_intake.status_code == random_intake.status_code == 404
    assert foreign_intake.json() == random_intake.json()
