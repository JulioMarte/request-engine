"""Appointment calendar: a bounded multi-week reservation read with claimed Resources.

Protected risk: a week/month calendar with doctor/room columns needs every
Reservation overlapping a window of up to 42 days together with the Resources
it consumes. Plausible regressions this must catch: the resource taken from the
wrong fact (another reservation's claim, a replaced claim, a resource merely
assigned to the location) or dropped after cancellation; keyset pages that skip
or repeat rows; a cursor reused with other filters; windows above 42 days or
without a timezone accepted; the read served without ``appointments.day_board``;
another organization's rows, subjects or resources leaking (HTTP and the view
under the runtime role); the view losing ``security_invoker`` or gaining writes.

Execution boundary: owner HTTP operations (slots, book, cancel, calendar) on the
real runtime and the least-privilege app role on PostgreSQL 18. Oracles:
authoritative ``capacity_claims``/``resources``/``reservations`` rows read with
the admin connection, never the calendar's own SQL.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, actor_for, auth, client_with_actors, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract]

WINDOW_START = datetime(2030, 1, 6, 0, 0, tzinfo=UTC)
WINDOW_END = datetime(2030, 1, 20, 0, 0, tzinfo=UTC)


def _calendar_actor(sandbox: TenantSandbox) -> ActorContext:
    base = actor_for(sandbox)
    return ActorContext(
        base.organization_id, base.principal_id, base.capabilities | {"appointments.day_board"}
    )


def _second_resource(conn: PgConnection, sandbox: TenantSandbox, name: str) -> UUID:
    """A second doctor who can serve the same offering at the same location (prerequisite)."""

    row = conn.execute(
        "INSERT INTO request_engine.resources "
        "(organization_id, resource_key, display_name, capacity_model, capacity_units) "
        "VALUES (%s, %s, %s, 'exclusive', 1) RETURNING id",
        (sandbox.organization_id, f"doctor-{uuid4().hex[:8]}", name),
    ).fetchone()
    assert row is not None
    resource_id = cast(UUID, row[0])
    conn.execute(
        "INSERT INTO request_engine.resource_capability_assignments "
        "(organization_id, resource_id, capability_id) "
        "SELECT organization_id, %s, capability_id "
        "FROM request_engine.offering_resource_requirements WHERE id = %s",
        (resource_id, sandbox.requirement_id),
    )
    assignment = conn.execute(
        "INSERT INTO request_engine.resource_location_assignments "
        "(organization_id, resource_id, location_id, effective_during) "
        "VALUES (%s, %s, %s, tstzrange('2000-01-01T00:00:00+00', NULL, '[)')) RETURNING id",
        (sandbox.organization_id, resource_id, sandbox.location_id),
    ).fetchone()
    assert assignment is not None
    conn.execute(
        "INSERT INTO request_engine.resource_location_availability "
        "(organization_id, resource_location_assignment_id, weekday, local_start, local_end) "
        "VALUES (%s, %s, 0, '09:00', '12:00')",
        (sandbox.organization_id, assignment[0]),
    )
    return resource_id


def _subject(conn: PgConnection, sandbox: TenantSandbox, name: str) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.parties (organization_id, party_kind, display_name) "
        "VALUES (%s, 'person', %s) RETURNING id",
        (sandbox.organization_id, name),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _slots(client: AsyncClient, sandbox: TenantSandbox, day: datetime) -> list[Any]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": day.replace(hour=13).isoformat(),
            "window_end": day.replace(hour=16).isoformat(),
        },
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    slots = cast(list[Any], response.json())
    assert slots, day
    return slots


async def _book(
    client: AsyncClient, sandbox: TenantSandbox, slot: dict[str, Any], subject: UUID
) -> dict[str, Any]:
    booked = await client.post(
        "/v1/appointments",
        json={"option_id": slot["option_id"], "subject_party_id": str(subject)},
        headers=auth(sandbox, idempotency_key=f"calendar-book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    return cast(dict[str, Any], booked.json())


def _window(**extra: str) -> dict[str, str]:
    return {"window_start": WINDOW_START.isoformat(), "window_end": WINDOW_END.isoformat(), **extra}


async def _all_pages(
    client: AsyncClient, sandbox: TenantSandbox, params: dict[str, str]
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    pages = 0
    cursor: str | None = None
    while True:
        query = {**params, **({"after": cursor} if cursor else {})}
        response = await client.get(
            "/v1/appointments/calendar", params=query, headers=auth(sandbox)
        )
        assert response.status_code == 200, response.text
        page = response.json()
        pages += 1
        rows.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return rows, pages
        assert pages < 20


def _claimed(conn: PgConnection, reservation_id: str) -> set[tuple[str, str, bool]]:
    rows = conn.execute(
        "SELECT c.resource_id, r.display_name, c.status = 'active' "
        "FROM request_engine.capacity_claims c "
        "JOIN request_engine.resources r ON r.id = c.resource_id "
        "WHERE c.reservation_id = %s AND c.status <> 'replaced'",
        (UUID(reservation_id),),
    ).fetchall()
    return {(str(row[0]), row[1], row[2]) for row in rows}


@pytest.mark.asyncio
async def test_calendar_returns_two_weeks_with_claimed_resources_and_stable_pages(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "calendar")
    other = seed_tenant_sandbox(e2e_admin_conn, "calendar-other")
    second = _second_resource(e2e_admin_conn, clinic, "Dra. Beatriz Calendario")
    subjects = [_subject(e2e_admin_conn, clinic, f"Paciente {index}") for index in range(5)]
    denied = ActorContext(
        clinic.organization_id, clinic.principal_id, actor_for(clinic).capabilities
    )
    actors = {
        clinic.token: _calendar_actor(clinic),
        other.token: _calendar_actor(other),
        "token-calendar-denied": denied,
    }
    week_one = datetime(2030, 1, 7, tzinfo=UTC)
    async with client_with_actors(e2e_session_factory, actors) as client:
        first_day = await _slots(client, clinic, week_one)
        # Two customers at the same instant: the exclusive resources force one each.
        same_time = await _book(client, clinic, first_day[0], subjects[0])
        repeat = await _slots(client, clinic, week_one)
        twin_slot = next(slot for slot in repeat if slot["start_at"] == first_day[0]["start_at"])
        twin = await _book(client, clinic, twin_slot, subjects[1])
        later = await _book(client, clinic, first_day[-1], subjects[2])
        week_two = await _book(
            client,
            clinic,
            (await _slots(client, clinic, week_one + timedelta(days=7)))[0],
            subjects[3],
        )
        outside = await _book(
            client,
            clinic,
            (await _slots(client, clinic, week_one + timedelta(days=14)))[0],
            subjects[4],
        )
        await _book(client, other, (await _slots(client, other, week_one))[0], other.party_id)
        cancelled = await client.post(
            f"/v1/appointments/{later['id']}/cancel",
            json={"expected_revision": later["revision"], "reason": "calendar proof"},
            headers=auth(clinic, idempotency_key=f"calendar-cancel-{uuid4().hex}"),
        )
        assert cancelled.status_code == 200, cancelled.text

        full = await client.get(
            "/v1/appointments/calendar", params=_window(limit="200"), headers=auth(clinic)
        )
        assert full.status_code == 200, full.text
        paged, pages = await _all_pages(client, clinic, _window(limit="2"))
        by_second = await client.get(
            "/v1/appointments/calendar",
            params=_window(resource_id=str(second)),
            headers=auth(clinic),
        )
        first_page = await client.get(
            "/v1/appointments/calendar", params=_window(limit="2"), headers=auth(clinic)
        )
        mismatched = await client.get(
            "/v1/appointments/calendar",
            params=_window(
                limit="2", resource_id=str(second), after=first_page.json()["next_cursor"]
            ),
            headers=auth(clinic),
        )
        too_long = await client.get(
            "/v1/appointments/calendar",
            params={
                "window_start": WINDOW_START.isoformat(),
                "window_end": (WINDOW_START + timedelta(days=42, seconds=1)).isoformat(),
            },
            headers=auth(clinic),
        )
        exactly_42 = await client.get(
            "/v1/appointments/calendar",
            params={
                "window_start": WINDOW_START.isoformat(),
                "window_end": (WINDOW_START + timedelta(days=42)).isoformat(),
            },
            headers=auth(clinic),
        )
        naive = await client.get(
            "/v1/appointments/calendar",
            params={"window_start": "2030-01-06T00:00:00", "window_end": "2030-01-20T00:00:00"},
            headers=auth(clinic),
        )
        without_capability = await client.get(
            "/v1/appointments/calendar",
            params=_window(),
            headers={"Authorization": "Bearer token-calendar-denied"},
        )
        foreign = await client.get(
            "/v1/appointments/calendar",
            params=_window(resource_id=str(clinic.resource_id)),
            headers=auth(other),
        )

    expected_ids = {same_time["id"], twin["id"], later["id"], week_two["id"]}
    items = cast(list[dict[str, Any]], full.json()["items"])
    assert full.json()["next_cursor"] is None
    assert {item["reservation_id"] for item in items} == expected_ids
    assert outside["id"] not in {item["reservation_id"] for item in items}
    # Order is (start_at, reservation_id), and paging with limit=2 yields the same rows.
    keys = [(datetime.fromisoformat(i["start_at"]), i["reservation_id"]) for i in items]
    assert keys == sorted(keys)
    assert [row["reservation_id"] for row in paged] == [item["reservation_id"] for item in items]
    assert pages == 2
    # Independent oracle: the authoritative current claim set and names.
    for item in items:
        shown = {
            (r["resource_id"], r["display_name"], r["claim_active"]) for r in item["resources"]
        }
        assert shown == _claimed(e2e_admin_conn, item["reservation_id"]), item
        assert len(shown) == 1
    by_id = {item["reservation_id"]: item for item in items}
    assert {
        next(iter(by_id[same_time["id"]]["resources"]))["resource_id"],
        next(iter(by_id[twin["id"]]["resources"]))["resource_id"],
    } == {str(clinic.resource_id), str(second)}
    cancelled_row = by_id[later["id"]]
    assert cancelled_row["status"] == "cancelled"
    assert cancelled_row["resources"][0]["claim_active"] is False
    assert by_id[same_time["id"]]["subject_display_name"] == "Paciente 0"
    offering_name = e2e_admin_conn.execute(
        "SELECT display_name FROM request_engine.offerings WHERE id = %s", (clinic.offering_id,)
    ).fetchone()
    assert offering_name is not None
    assert {item["offering_display_name"] for item in items} == {offering_name[0]}
    assert all(item["served_at"] is None and item["checked_in_at"] is None for item in items)
    # Resource filter returns exactly the reservations whose claim set uses it.
    second_ids = {
        str(row[0])
        for row in e2e_admin_conn.execute(
            "SELECT DISTINCT reservation_id FROM request_engine.capacity_claims "
            "WHERE resource_id = %s AND status <> 'replaced' AND reservation_id IS NOT NULL",
            (second,),
        ).fetchall()
    } & expected_ids
    assert by_second.status_code == 200, by_second.text
    assert {i["reservation_id"] for i in by_second.json()["items"]} == second_ids
    assert second_ids and second_ids != expected_ids
    # Validation and authority failures.
    assert mismatched.status_code == 422, mismatched.text
    assert too_long.status_code == 422, too_long.text
    assert exactly_42.status_code == 200, exactly_42.text
    assert naive.status_code == 422, naive.text
    assert without_capability.status_code == 403, without_capability.text
    # The other organization never sees the clinic's rows, even filtering by its resource.
    assert foreign.status_code == 200, foreign.text
    assert foreign.json()["items"] == []
    assert "Paciente" not in foreign.text and "Beatriz" not in foreign.text

    statement = text(
        "SELECT reservation_id FROM request_read.reservation_calendar_v1 "
        "WHERE reservation_id = :reservation_id"
    )
    async with tenant_transaction(e2e_session_factory, other.organization_id) as session:
        leaked = (await session.execute(statement, {"reservation_id": same_time["id"]})).all()
        claimed_elsewhere = (
            await session.execute(
                text(
                    "SELECT count(*) FROM request_read.reservation_calendar_v1 "
                    "WHERE claimed_resource_ids && ARRAY[CAST(:a AS uuid), CAST(:b AS uuid)]"
                ),
                {"a": clinic.resource_id, "b": second},
            )
        ).scalar_one()
    assert leaked == [] and claimed_elsewhere == 0


def test_calendar_view_is_security_invoker_read_only_and_indexed(
    e2e_admin_conn: PgConnection,
) -> None:
    row = e2e_admin_conn.execute(
        """
        SELECT c.reloptions, pg_catalog.pg_get_userbyid(c.relowner),
               has_table_privilege('request_engine_app', c.oid, 'SELECT'),
               has_table_privilege('request_engine_app', c.oid, 'INSERT'),
               has_table_privilege('request_engine_app', c.oid, 'UPDATE'),
               has_table_privilege('public', c.oid, 'SELECT')
          FROM pg_catalog.pg_class c
          JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'request_read' AND c.relname = 'reservation_calendar_v1'
        """
    ).fetchone()
    assert row is not None
    options, owner, can_select, can_insert, can_update, public_select = row
    assert "security_invoker=true" in (options or [])
    assert owner == "request_engine_schema_owner"
    assert (can_select, can_insert, can_update, public_select) == (True, False, False, False)
    index = e2e_admin_conn.execute(
        "SELECT i.indisvalid FROM pg_catalog.pg_index i "
        "JOIN pg_catalog.pg_class c ON c.oid = i.indexrelid "
        "WHERE c.relname = 'capacity_claims_reservation_current_idx'"
    ).fetchone()
    assert index == (True,)
