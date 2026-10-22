"""Front-desk staffing read: a receptionist can choose who serves a called customer.

Protected risk: the only resource read used to require an
``operations.manage_supply`` Party representation, so a receptionist with
delegated ``queue.*`` and ``service_session.start`` could never start a
service. ``front_desk_serving_resources`` must list exactly the Resources that
``service_session.start`` accepts at the Location now, gated by that same
capability. Plausible regressions this must catch: inactive Resources,
Resources without an assignment, retired/future/other-location assignments
being offered (the start would then fail); the read requiring supply authority
again or being served without ``service_session.start``; another
organization's Location answering.

Execution boundary: owner HTTP operations on the real runtime (book, check in,
call, serving-resources, start) over PostgreSQL 18. The receptionist actor holds
no supply capability and the principal has no ``operations.manage_supply``
representation (asserted). Oracle for the list: the resources the scenario set
up, chosen independently of the reader SQL; for the start: the authoritative
``service_sessions`` row.
"""

from typing import cast
from uuid import UUID, uuid4

import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .front_desk_recall_support import book_and_check_in, front_desk_actor
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract]

RECEPTIONIST_CAPABILITIES = frozenset(
    {"queue.staff_read", "queue.call_next", "service_session.start", "service_session.complete"}
)


def _resource(
    conn: PgConnection,
    sandbox: TenantSandbox,
    name: str,
    *,
    active: bool = True,
    location_id: UUID | None = None,
    during: str | None = "[2000-01-01T00:00:00+00,)",
    status: str = "active",
) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.resources "
        "(organization_id, resource_key, display_name, capacity_model, capacity_units, active) "
        "VALUES (%s, %s, %s, 'exclusive', 1, %s) RETURNING id",
        (sandbox.organization_id, f"r-{uuid4().hex[:10]}", name, active),
    ).fetchone()
    assert row is not None
    resource_id = cast(UUID, row[0])
    if during is not None:
        conn.execute(
            "INSERT INTO request_engine.resource_location_assignments "
            "(organization_id, resource_id, location_id, effective_during, status) "
            "VALUES (%s, %s, %s, CAST(%s AS tstzrange), %s)",
            (
                sandbox.organization_id,
                resource_id,
                location_id or sandbox.location_id,
                during,
                status,
            ),
        )
    return resource_id


def _second_location(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.locations "
        "(organization_id, location_key, display_name, timezone, public_data) "
        "VALUES (%s, %s, 'Sede Norte', 'America/Santo_Domingo', '{}'::jsonb) RETURNING id",
        (sandbox.organization_id, f"north-{uuid4().hex[:8]}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.asyncio
async def test_receptionist_without_supply_authority_lists_who_serves_and_starts_service(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "serving")
    other = seed_tenant_sandbox(e2e_admin_conn, "serving-other")
    north = _second_location(e2e_admin_conn, clinic)
    on_duty = _resource(e2e_admin_conn, clinic, "Dra. Ana Turno")
    _resource(e2e_admin_conn, clinic, "Dr. Inactivo", active=False)
    _resource(e2e_admin_conn, clinic, "Dr. Sin Sede", during=None)
    _resource(e2e_admin_conn, clinic, "Dr. Retirado", status="retired")
    _resource(
        e2e_admin_conn,
        clinic,
        "Dr. Vencido",
        during="[2000-01-01T00:00:00+00,2001-01-01T00:00:00+00)",
    )
    _resource(e2e_admin_conn, clinic, "Dr. Futuro", during="[2999-01-01T00:00:00+00,)")
    _resource(e2e_admin_conn, clinic, "Dr. Norte", location_id=north)
    owner = front_desk_actor(clinic)
    receptionist = ActorContext(
        clinic.organization_id, clinic.principal_id, RECEPTIONIST_CAPABILITIES
    )
    no_start = ActorContext(
        clinic.organization_id,
        clinic.principal_id,
        RECEPTIONIST_CAPABILITIES - {"service_session.start"},
    )
    actors = {
        clinic.token: owner,
        "token-receptionist": receptionist,
        "token-no-start": no_start,
        other.token: ActorContext(
            other.organization_id, other.principal_id, RECEPTIONIST_CAPABILITIES
        ),
    }
    desk = {"Authorization": "Bearer token-receptionist"}
    supply_representations = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.representations "
        "WHERE organization_id = %s AND principal_id = %s "
        "AND scope_key = 'operations.manage_supply'",
        (clinic.organization_id, clinic.principal_id),
    ).fetchone()
    assert supply_representations == (0,)
    path = f"/v1/locations/{clinic.location_id}/serving-resources"
    async with client_with_actors(e2e_session_factory, actors) as client:
        _, entry = await book_and_check_in(client, clinic)
        supply = await client.get(
            "/v1/booking/resources",
            params={"authority_party_id": str(clinic.party_id)},
            headers=desk,
        )
        listed = await client.get(path, headers=desk)
        denied = await client.get(path, headers={"Authorization": "Bearer token-no-start"})
        unknown = await client.get(f"/v1/locations/{uuid4()}/serving-resources", headers=desk)
        foreign = await client.get(path, headers=auth(other))
        north_listed = await client.get(f"/v1/locations/{north}/serving-resources", headers=desk)
        called = await client.post(
            f"/v1/queues/{clinic.queue_id}/call-next",
            headers={**desk, "Idempotency-Key": f"serving-call-{uuid4().hex}"},
        )
        assert called.status_code == 200, called.text
        assert called.json()["id"] == entry["id"]
        choice = next(i for i in listed.json()["items"] if i["display_name"] == "Dra. Ana Turno")
        started = await client.post(
            f"/v1/queue-entries/{entry['id']}/service/start",
            json={
                "resource_id": choice["resource_id"],
                "location_id": listed.json()["location_id"],
                "expected_queue_revision": called.json()["revision"],
            },
            headers={**desk, "Idempotency-Key": f"serving-start-{uuid4().hex}"},
        )

    # The supply read stays owner-only; the receptionist is not granted it.
    assert supply.status_code == 403, supply.text
    assert listed.status_code == 200, listed.text
    names = [item["display_name"] for item in listed.json()["items"]]
    sandbox_name = e2e_admin_conn.execute(
        "SELECT display_name FROM request_engine.resources WHERE id = %s", (clinic.resource_id,)
    ).fetchone()
    assert sandbox_name is not None
    assert sorted(names, key=str.lower) == names
    assert set(names) == {"Dra. Ana Turno", sandbox_name[0]}
    assert {item["resource_id"] for item in listed.json()["items"]} == {
        str(on_duty),
        str(clinic.resource_id),
    }
    assert listed.json()["location_id"] == str(clinic.location_id)
    assert [i["display_name"] for i in north_listed.json()["items"]] == ["Dr. Norte"]
    assert denied.status_code == 403, denied.text
    assert unknown.status_code == 404, unknown.text
    assert foreign.status_code == 404, foreign.text
    assert "Ana Turno" not in foreign.text
    # The receptionist started service through the real owner path with that choice.
    assert started.status_code == 201, started.text
    session = e2e_admin_conn.execute(
        "SELECT resource_id, location_id, status FROM request_engine.service_sessions "
        "WHERE queue_entry_id = %s",
        (UUID(entry["id"]),),
    ).fetchone()
    assert session == (on_duty, clinic.location_id, "active")
