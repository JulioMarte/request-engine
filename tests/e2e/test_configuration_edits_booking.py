"""Booking owner configuration edits: Resource rename, capability set, absences.

Protected risks (plausible regressions that must turn this red):

* a capability replacement that silently cancels/rewrites an existing confirmed
  Reservation or its CapacityClaims, or that does not change future eligibility
  (slot search keeps offering a removed capability / ignores an added one);
* removing a capability while a live Hold depends on it (the Hold confirmation
  would later fail inside ``guard_capacity_claim``);
* not serializing on the Resource capacity root, so two replacements with the
  same expected revision both win (lost update) or the revision steps twice;
* foreign capabilities/resources accepted, the command running without
  ``booking.manage_supply`` or without exact Party authority, replay creating a
  second effect, or a reused key with a different body accepted;
* a rename advancing ``availability_revision`` (it is not availability-material)
  or leaking the label into the outbox;
* a deactivated Resource-wide absence still blocking slots, being deleted
  (losing audit history) or not advancing the availability revision.

Execution boundary: the real HTTP application with the least-privilege runtime
role on PostgreSQL 18. Oracles: authoritative rows read with the admin
connection (``resources``, ``resource_capability_assignments``,
``capacity_claims``, ``reservations``, ``schedule_exceptions``,
``outbox_messages``, ``audit_records``), never the reader under test.
"""

import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import (
    TenantSandbox,
    actor_for,
    client_with_actors,
    seed_tenant_sandbox,
)

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

DAY = datetime(2030, 1, 7, tzinfo=UTC)
SUPPLY = frozenset({"booking.manage_supply", "booking.read_supply"})


def _grant_supply_authority(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(organization_id, principal_id, "
        "principal_plane, authority_plane, capability_key, granted_by_principal_id, "
        "provenance_kind, provenance_reference) VALUES (%s, %s, 'tenant', 'operational', "
        "'booking.read_supply', %s, 'operator', 'configuration read grant')",
        (sandbox.organization_id, sandbox.principal_id, sandbox.principal_id),
    )
    conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'delegated', 'operations.manage_supply',
                  clock_timestamp() + interval '1 day')
        """,
        (sandbox.organization_id, sandbox.principal_id, sandbox.party_id),
    )


def _client(
    factory: SessionFactory, *sandboxes: TenantSandbox, without_supply: bool = False
) -> AsyncClient:
    actors: dict[str, ActorContext] = {}
    for sandbox in sandboxes:
        base = actor_for(sandbox)
        extra: frozenset[str] = frozenset() if without_supply else SUPPLY
        actors[sandbox.token] = replace(base, capabilities=base.capabilities | extra)
    return client_with_actors(factory, actors)


def _headers(sandbox: TenantSandbox, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {sandbox.token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _revision(conn: PgConnection, resource_id: UUID) -> int:
    row = conn.execute(
        "SELECT availability_revision FROM request_engine.resources WHERE id = %s",
        (resource_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _links(conn: PgConnection, resource_id: UUID) -> set[UUID]:
    return {
        cast(UUID, row[0])
        for row in conn.execute(
            "SELECT capability_id FROM request_engine.resource_capability_assignments "
            "WHERE resource_id = %s",
            (resource_id,),
        ).fetchall()
    }


def _capability_id(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "SELECT capability_id FROM request_engine.offering_resource_requirements WHERE id = %s",
        (sandbox.requirement_id,),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _new_capability(conn: PgConnection, sandbox: TenantSandbox, key: str) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.resource_capabilities "
        "(organization_id, capability_key, display_name) VALUES (%s, %s, %s) RETURNING id",
        (sandbox.organization_id, f"{key}-{uuid4().hex[:8]}", f"Capability {key}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _offering_requiring(conn: PgConnection, sandbox: TenantSandbox, capability_id: UUID) -> UUID:
    """A valid second bookable Offering whose single requirement is ``capability_id``."""

    suffix = uuid4().hex[:10]
    offering = conn.execute(
        "INSERT INTO request_engine.offerings (organization_id, offering_key, display_name) "
        "VALUES (%s, %s, %s) RETURNING id",
        (sandbox.organization_id, f"second-{suffix}", f"Second {suffix}"),
    ).fetchone()
    assert offering is not None
    version = conn.execute(
        "INSERT INTO request_engine.offering_versions (organization_id, offering_id, version, "
        "duration_minutes, bookable, requestable, booking_policy, public_data) "
        "VALUES (%s, %s, 1, 30, true, true, %s::jsonb, '{}'::jsonb) RETURNING id",
        (sandbox.organization_id, offering[0], json.dumps({"slot_step_minutes": 30})),
    ).fetchone()
    assert version is not None
    conn.execute(
        "INSERT INTO request_engine.offering_resource_requirements "
        "(organization_id, offering_version_id, capability_id, ordinal, quantity) "
        "VALUES (%s, %s, %s, 1, 1)",
        (sandbox.organization_id, version[0], capability_id),
    )
    conn.execute(
        "INSERT INTO request_engine.offering_version_booking_terms "
        "(organization_id, offering_version_id, amount, currency) VALUES (%s, %s, 1500, 'DOP')",
        (sandbox.organization_id, version[0]),
    )
    return cast(UUID, version[0])


async def _slots(
    client: AsyncClient, sandbox: TenantSandbox, offering_version_id: UUID
) -> list[dict[str, Any]]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": DAY.replace(hour=13).isoformat(),
            "window_end": DAY.replace(hour=16).isoformat(),
        },
        headers=_headers(sandbox),
    )
    assert response.status_code == 200, response.text
    return cast(list[dict[str, Any]], response.json())


async def _replace(
    client: AsyncClient,
    sandbox: TenantSandbox,
    capability_ids: list[UUID],
    expected: int,
    key: str | None = None,
    resource_id: UUID | None = None,
) -> Any:
    return await client.put(
        f"/v1/operations/resources/{resource_id or sandbox.resource_id}/capabilities",
        json={
            "authority_party_id": str(sandbox.party_id),
            "capability_ids": [str(value) for value in capability_ids],
            "expected_resource_availability_revision": expected,
        },
        headers=_headers(sandbox, key or f"caps-{uuid4().hex}"),
    )


def _outbox(conn: PgConnection, resource_id: UUID, event_type: str) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], row[0])
        for row in conn.execute(
            "SELECT payload FROM request_engine.outbox_messages "
            "WHERE aggregate_id = %s AND event_type = %s ORDER BY created_at",
            (resource_id, event_type),
        ).fetchall()
    ]


@pytest.mark.asyncio
async def test_capability_replacement_changes_future_eligibility_and_retains_commitments(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "caps")
    _grant_supply_authority(e2e_admin_conn, clinic)
    cap_a = _capability_id(e2e_admin_conn, clinic)
    cap_b = _new_capability(e2e_admin_conn, clinic, "b")
    second_version = _offering_requiring(e2e_admin_conn, clinic, cap_b)
    start = _revision(e2e_admin_conn, clinic.resource_id)

    async with _client(e2e_session_factory, clinic) as client:
        assert await _slots(client, clinic, second_version) == []

        added = await _replace(client, clinic, [cap_b, cap_a], start)
        assert added.status_code == 200, added.text
        body = added.json()
        assert set(body["capability_ids"]) == {str(cap_a), str(cap_b)}
        assert body["capability_ids"] == sorted(body["capability_ids"])
        assert body["added_capability_ids"] == [str(cap_b)]
        assert body["removed_capability_ids"] == []
        assert body["retained_commitment_count"] == 0
        assert body["availability_revision"] == start + 1
        assert _revision(e2e_admin_conn, clinic.resource_id) == start + 1
        assert _links(e2e_admin_conn, clinic.resource_id) == {cap_a, cap_b}
        assert await _slots(client, clinic, second_version)

        # A confirmed Reservation that relies on capability A.
        slots = await _slots(client, clinic, clinic.offering_version_id)
        booked = await client.post(
            "/v1/appointments",
            json={"option_id": slots[0]["option_id"], "subject_party_id": str(clinic.party_id)},
            headers=_headers(clinic, f"caps-book-{uuid4().hex}"),
        )
        assert booked.status_code == 201, booked.text
        reservation_id = UUID(booked.json()["id"])
        before_reservation = e2e_admin_conn.execute(
            "SELECT status, revision, during FROM request_engine.reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()
        before_claims = e2e_admin_conn.execute(
            "SELECT id, status, resource_id, during FROM request_engine.capacity_claims "
            "WHERE reservation_id = %s ORDER BY id",
            (reservation_id,),
        ).fetchall()
        assert before_claims

        revision = _revision(e2e_admin_conn, clinic.resource_id)
        removed = await _replace(client, clinic, [cap_b], revision)
        assert removed.status_code == 200, removed.text
        assert removed.json()["removed_capability_ids"] == [str(cap_a)]
        assert removed.json()["added_capability_ids"] == []
        assert removed.json()["retained_commitment_count"] == 1
        assert removed.json()["availability_revision"] == revision + 1
        assert _links(e2e_admin_conn, clinic.resource_id) == {cap_b}

        # Existing commitment untouched; future search no longer offers capability A.
        assert (
            e2e_admin_conn.execute(
                "SELECT status, revision, during FROM request_engine.reservations WHERE id = %s",
                (reservation_id,),
            ).fetchone()
            == before_reservation
        )
        assert (
            e2e_admin_conn.execute(
                "SELECT id, status, resource_id, during FROM request_engine.capacity_claims "
                "WHERE reservation_id = %s ORDER BY id",
                (reservation_id,),
            ).fetchall()
            == before_claims
        )
        assert await _slots(client, clinic, clinic.offering_version_id) == []

        # Same set again: no revision step, still a recorded 200.
        same = await _replace(client, clinic, [cap_b], revision + 1)
        assert same.status_code == 200, same.text
        assert same.json()["availability_revision"] == revision + 1
        assert same.json()["added_capability_ids"] == same.json()["removed_capability_ids"] == []

    events = _outbox(e2e_admin_conn, clinic.resource_id, "resource.capabilities_replaced.v1")
    assert len(events) == 3
    assert events[1]["removed_capability_ids"] == [str(cap_a)]
    assert all("display_name" not in json.dumps(event) for event in events)


@pytest.mark.asyncio
async def test_capability_removal_refuses_while_a_live_hold_depends_on_it(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "caps-hold")
    other = seed_tenant_sandbox(e2e_admin_conn, "caps-hold-other")
    _grant_supply_authority(e2e_admin_conn, clinic)
    cap_a = _capability_id(e2e_admin_conn, clinic)
    cap_b = _new_capability(e2e_admin_conn, clinic, "b")
    foreign_cap = _capability_id(e2e_admin_conn, other)
    # Valid live Hold precondition: the claim passes the real guard_capacity_claim.
    with e2e_admin_conn.transaction():
        hold = e2e_admin_conn.execute(
            "INSERT INTO request_engine.capacity_holds (organization_id, offering_version_id, "
            "subject_party_id, location_id, during, expires_at) VALUES (%s, %s, %s, %s, "
            "tstzrange('2030-01-07T13:00Z', '2030-01-07T13:30Z', '[)'), "
            "clock_timestamp() + interval '10 minutes') RETURNING id",
            (
                clinic.organization_id,
                clinic.offering_version_id,
                clinic.party_id,
                clinic.location_id,
            ),
        ).fetchone()
        assert hold is not None
        e2e_admin_conn.execute(
            "INSERT INTO request_engine.capacity_claims (organization_id, resource_id, "
            "requirement_id, hold_id, during, quantity) VALUES (%s, %s, %s, %s, "
            "tstzrange('2030-01-07T13:00Z', '2030-01-07T13:30Z', '[)'), 1)",
            (clinic.organization_id, clinic.resource_id, clinic.requirement_id, hold[0]),
        )
    start = _revision(e2e_admin_conn, clinic.resource_id)

    async with _client(e2e_session_factory, clinic) as client:
        refused = await _replace(client, clinic, [cap_b], start)
        assert refused.status_code == 409, refused.text
        error = refused.json()["error"]
        assert error["code"] == "resource_capability_held"
        assert error["details"]["capability_ids"] == [str(cap_a)]

        foreign = await _replace(client, clinic, [cap_a, foreign_cap], start)
        assert foreign.status_code == 409, foreign.text
        assert foreign.json()["error"]["code"] == "contextual_configuration_conflict"

        foreign_resource = await _replace(
            client, clinic, [cap_a], start, resource_id=other.resource_id
        )
        assert foreign_resource.status_code == 409, foreign_resource.text
        assert foreign_resource.json()["error"]["code"] == "contextual_configuration_conflict"

        duplicate = await _replace(client, clinic, [cap_a, cap_a], start)
        assert duplicate.status_code == 422, duplicate.text

        # Adding while the Hold lives is fine: nothing it depends on is removed.
        added = await _replace(client, clinic, [cap_a, cap_b], start)
        assert added.status_code == 200, added.text

    assert _links(e2e_admin_conn, clinic.resource_id) == {cap_a, cap_b}
    assert _revision(e2e_admin_conn, clinic.resource_id) == start + 1
    assert _links(e2e_admin_conn, other.resource_id) == {foreign_cap}


@pytest.mark.asyncio
async def test_resource_rename_is_authorized_idempotent_and_not_availability_material(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "rename")
    other = seed_tenant_sandbox(e2e_admin_conn, "rename-other")
    _grant_supply_authority(e2e_admin_conn, clinic)
    start = _revision(e2e_admin_conn, clinic.resource_id)
    url = f"/v1/operations/resources/{clinic.resource_id}"
    body = {
        "authority_party_id": str(clinic.party_id),
        "display_name": "  Dra. Pérez  ",
        "expected_resource_availability_revision": start,
    }
    key = f"rename-{uuid4().hex}"

    async with _client(e2e_session_factory, clinic) as client:
        renamed = await client.patch(url, json=body, headers=_headers(clinic, key))
        assert renamed.status_code == 200, renamed.text
        assert renamed.json()["display_name"] == "Dra. Pérez"
        assert renamed.json()["availability_revision"] == start
        replay = await client.patch(url, json=body, headers=_headers(clinic, key))
        assert replay.status_code == 200
        assert replay.json() == renamed.json()
        reused = await client.patch(
            url, json={**body, "display_name": "Otro"}, headers=_headers(clinic, key)
        )
        assert reused.status_code == 409, reused.text
        stale = await client.patch(
            url,
            json={**body, "expected_resource_availability_revision": start + 5},
            headers=_headers(clinic, f"rename-{uuid4().hex}"),
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "resource_availability_revision_conflict"
        blank = await client.patch(
            url, json={**body, "display_name": "   "}, headers=_headers(clinic, "blank")
        )
        assert blank.status_code == 422
        foreign = await client.patch(
            f"/v1/operations/resources/{other.resource_id}",
            json=body,
            headers=_headers(clinic, f"rename-{uuid4().hex}"),
        )
        assert foreign.status_code == 409
        assert foreign.json()["error"]["code"] == "contextual_configuration_conflict"

    async with _client(e2e_session_factory, clinic, without_supply=True) as denied_client:
        denied = await denied_client.patch(
            url, json=body, headers=_headers(clinic, f"rename-{uuid4().hex}")
        )
        assert denied.status_code == 403, denied.text

    row = e2e_admin_conn.execute(
        "SELECT display_name, availability_revision FROM request_engine.resources WHERE id = %s",
        (clinic.resource_id,),
    ).fetchone()
    assert row == ("Dra. Pérez", start)
    other_row = e2e_admin_conn.execute(
        "SELECT display_name FROM request_engine.resources WHERE id = %s", (other.resource_id,)
    ).fetchone()
    assert other_row is not None and other_row[0] != "Dra. Pérez"
    events = _outbox(e2e_admin_conn, clinic.resource_id, "resource.updated.v1")
    assert len(events) == 1
    assert "Pérez" not in json.dumps(events[0])
    audits = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE aggregate_id = %s AND command_name = 'booking.update_resource'",
        (clinic.resource_id,),
    ).fetchone()
    assert audits == (1,)


async def _wait_for_blocked(observer: PgConnection, blocker_pid: int, count: int) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        # The first replacement waits on the barrier's row lock; later ones queue behind
        # it on the same Resource tuple. All must be waiting on the Resource row.
        rows = observer.execute(
            "SELECT query, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock' "
            "AND cardinality(pg_blocking_pids(pid)) > 0",
        ).fetchall()
        waiting = [str(row[0]) for row in rows]
        direct = [row for row in rows if blocker_pid in row[1]]
        if len(waiting) >= count and direct:
            assert all("FROM request_engine.resources" in query for query in waiting), waiting
            return
        await asyncio.sleep(0.025)
    activity = observer.execute(
        "SELECT pid, state, wait_event_type, wait_event, pg_blocking_pids(pid), left(query, 120) "
        "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"
    ).fetchall()
    raise AssertionError(f"capability replacements did not wait on the Resource root: {activity}")


@pytest.mark.asyncio
async def test_concurrent_replacements_serialize_on_the_resource_root(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: psycopg.Connection[Any],
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "caps-race")
    _grant_supply_authority(e2e_admin_conn, clinic)
    cap_a = _capability_id(e2e_admin_conn, clinic)
    cap_b = _new_capability(e2e_admin_conn, clinic, "b")
    cap_c = _new_capability(e2e_admin_conn, clinic, "c")
    start = _revision(e2e_admin_conn, clinic.resource_id)

    blocker_pid = cast(
        int,
        e2e_barrier_conn.execute("SELECT pg_backend_pid()").fetchone()[0],  # type: ignore[index]
    )
    e2e_barrier_conn.execute(
        "SELECT id FROM request_engine.resources WHERE id = %s FOR UPDATE",
        (clinic.resource_id,),
    )
    async with _client(e2e_session_factory, clinic) as client:
        first = asyncio.create_task(_replace(client, clinic, [cap_a, cap_b], start))
        second = asyncio.create_task(_replace(client, clinic, [cap_a, cap_c], start))
        try:
            await _wait_for_blocked(e2e_admin_conn, blocker_pid, 2)
            assert not first.done() and not second.done()
        finally:
            e2e_barrier_conn.rollback()
        results = await asyncio.gather(first, second)

    statuses = sorted(result.status_code for result in results)
    assert statuses == [200, 409], [result.text for result in results]
    loser = next(result for result in results if result.status_code == 409)
    assert loser.json()["error"]["code"] == "resource_availability_revision_conflict"
    winner = next(result for result in results if result.status_code == 200)
    assert _revision(e2e_admin_conn, clinic.resource_id) == start + 1
    assert {str(value) for value in _links(e2e_admin_conn, clinic.resource_id)} == set(
        winner.json()["capability_ids"]
    )


@pytest.mark.asyncio
async def test_resource_absence_deactivation_restores_slots_and_keeps_the_row(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "absence")
    _grant_supply_authority(e2e_admin_conn, clinic)
    url = f"/v1/operations/resources/{clinic.resource_id}/exceptions"
    absence = {
        "authority_party_id": str(clinic.party_id),
        "start_at": DAY.replace(hour=13).isoformat(),
        "end_at": DAY.replace(hour=16).isoformat(),
        "exception_kind": "unavailable",
        "reason": "Vacaciones",
    }

    async with _client(e2e_session_factory, clinic) as client:
        open_slots = await _slots(client, clinic, clinic.offering_version_id)
        assert open_slots
        start = _revision(e2e_admin_conn, clinic.resource_id)
        created = await client.put(
            url,
            json={**absence, "expected_resource_availability_revision": start},
            headers=_headers(clinic, f"absence-{uuid4().hex}"),
        )
        assert created.status_code == 200, created.text
        assert created.json()["active"] is True
        exception_id = created.json()["exception_id"]
        assert await _slots(client, clinic, clinic.offering_version_id) == []

        no_id = await client.put(
            url,
            json={
                **absence,
                "active": False,
                "expected_resource_availability_revision": start + 1,
            },
            headers=_headers(clinic, f"absence-{uuid4().hex}"),
        )
        assert no_id.status_code == 422, no_id.text

        removed = await client.put(
            url,
            json={
                **absence,
                "exception_id": exception_id,
                "active": False,
                "expected_resource_availability_revision": start + 1,
            },
            headers=_headers(clinic, f"absence-{uuid4().hex}"),
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["active"] is False
        assert removed.json()["resource_availability_revision"] == start + 2
        assert len(await _slots(client, clinic, clinic.offering_version_id)) == len(open_slots)

        listed = await client.get(
            f"/v1/booking/resources/{clinic.resource_id}/exceptions",
            params={"authority_party_id": str(clinic.party_id)},
            headers=_headers(clinic),
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert [(item["exception_id"], item["active"]) for item in items] == [(exception_id, False)]

    row = e2e_admin_conn.execute(
        "SELECT active, reason FROM request_engine.schedule_exceptions WHERE id = %s",
        (UUID(exception_id),),
    ).fetchone()
    assert row == (False, "Vacaciones")
    assert _revision(e2e_admin_conn, clinic.resource_id) == start + 2
