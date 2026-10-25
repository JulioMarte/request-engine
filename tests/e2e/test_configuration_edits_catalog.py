"""Catalog configuration edits after creation (owner commands on PostgreSQL 18).

Protected risks (plausible regressions that must turn this red):

* a Location rename advancing ``operational_revision`` (it is not booking-material)
  or being lost on replay;
* an Offering rename without compare-and-set on ``offerings.revision``;
* a duration/price change rewriting an existing OfferingVersion, its terms or an
  existing Reservation instead of appending version N+1 (immutable history);
* a new version not copying requirements, flags or the *effective* booking policy;
* two concurrent supersessions both creating a version (lost serialization on the
  Offering root);
* a removed hours exception/holiday being deleted instead of deactivated, other
  dates being touched, or exceptions of another tenant becoming visible/mutable;
* idempotent replay creating a second effect or a reused key with a different body
  being accepted; missing capability not denied;
* outbox change facts carrying names or reasons.

Execution boundary: the real HTTP application with the least-privilege runtime role.
Oracles: authoritative rows read with the admin connection.
"""

import asyncio
import json
import time
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from httpx import AsyncClient

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .operator_journey_support import (
    OPERATIONAL_CAPABILITIES,
    grant_operational_scopes,
    operator_actor,
)
from .tenant_sandbox import TenantSandbox, client_with_actors, first_slot, seed_tenant_sandbox

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

_READ = "catalog.read_configuration"


def _grant_read(conn: PgConnection, sandbox: TenantSandbox) -> None:
    conn.execute(
        "INSERT INTO request_engine.principal_authority_grants(organization_id,"
        "principal_id,principal_plane,authority_plane,capability_key,"
        "granted_by_principal_id,provenance_kind,provenance_reference) "
        "VALUES(%s,%s,'tenant','operational',%s,%s,'operator','configuration edits proof')",
        (sandbox.organization_id, sandbox.principal_id, _READ, sandbox.principal_id),
    )


def _world(conn: PgConnection, prefix: str) -> TenantSandbox:
    sandbox = seed_tenant_sandbox(conn, prefix)
    grant_operational_scopes(conn, sandbox)
    _grant_read(conn, sandbox)
    return sandbox


def _client(
    factory: SessionFactory, *sandboxes: TenantSandbox, without_manage: bool = False
) -> AsyncClient:
    actors: dict[str, ActorContext] = {}
    for sandbox in sandboxes:
        actor = operator_actor(sandbox, capabilities=OPERATIONAL_CAPABILITIES | {_READ})
        if without_manage:
            actor = replace(actor, capabilities=actor.capabilities - {"catalog.manage"})
        actors[sandbox.token] = actor
    return client_with_actors(factory, actors)


def _headers(sandbox: TenantSandbox, key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {sandbox.token}"}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _scalar(conn: PgConnection, query: str, *params: object) -> Any:
    row = conn.execute(query, params).fetchone()  # type: ignore[arg-type]
    assert row is not None
    return row[0]


def _outbox(conn: PgConnection, aggregate_id: UUID, event_type: str) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], row[0])
        for row in conn.execute(
            "SELECT payload FROM request_engine.outbox_messages "
            "WHERE aggregate_id = %s AND event_type = %s ORDER BY created_at",
            (aggregate_id, event_type),
        ).fetchall()
    ]


@pytest.mark.asyncio
async def test_location_rename_keeps_operational_revision_and_replays(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = _world(e2e_admin_conn, "loc-rename")
    revision = cast(
        int,
        _scalar(
            e2e_admin_conn,
            "SELECT operational_revision FROM request_engine.locations WHERE id = %s",
            clinic.location_id,
        ),
    )
    url = f"/v1/operations/locations/{clinic.location_id}"
    body = {
        "authority_party_id": str(clinic.party_id),
        "timezone": "America/Santo_Domingo",
        "active": True,
        "expected_operational_revision": revision,
        "display_name": "  Sede Piantini  ",
    }
    key = f"loc-{uuid4().hex}"
    async with _client(e2e_session_factory, clinic) as client:
        first = await client.patch(url, json=body, headers=_headers(clinic, key))
        replay = await client.patch(url, json=body, headers=_headers(clinic, key))
        blank = await client.patch(
            url,
            json={**body, "display_name": "   "},
            headers=_headers(clinic, f"loc-{uuid4().hex}"),
        )
        keep = await client.patch(
            url,
            json={**body, "display_name": None},
            headers=_headers(clinic, f"loc-{uuid4().hex}"),
        )

    assert first.status_code == 200, first.text
    assert first.json()["display_name"] == "Sede Piantini"
    assert first.json()["operational_revision"] == revision
    assert replay.json() == first.json()
    assert blank.status_code == 422, blank.text
    assert keep.status_code == 200 and keep.json()["display_name"] == "Sede Piantini"
    row = e2e_admin_conn.execute(
        "SELECT display_name, operational_revision FROM request_engine.locations WHERE id = %s",
        (clinic.location_id,),
    ).fetchone()
    assert row == ("Sede Piantini", revision)
    # The existing Location update keeps its audit-only effect contract (no outbox fact).
    assert _outbox(e2e_admin_conn, clinic.location_id, "catalog.location_updated.v1") == []


@pytest.mark.asyncio
async def test_offering_rename_is_compare_and_set_and_tenant_opaque(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = _world(e2e_admin_conn, "off-rename")
    other = _world(e2e_admin_conn, "off-rename-other")
    url = f"/v1/operations/offerings/{clinic.offering_id}"
    async with _client(e2e_session_factory, clinic, other) as client:
        read = await client.get(
            f"/v1/catalog/offerings/{clinic.offering_id}/configuration",
            params={"authority_party_id": str(clinic.party_id)},
            headers=_headers(clinic),
        )
        assert read.status_code == 200, read.text
        assert read.json()["revision"] == 1
        body = {
            "authority_party_id": str(clinic.party_id),
            "display_name": "Limpieza dental",
            "expected_revision": 1,
        }
        key = f"off-{uuid4().hex}"
        first = await client.patch(url, json=body, headers=_headers(clinic, key))
        replay = await client.patch(url, json=body, headers=_headers(clinic, key))
        reused = await client.patch(
            url, json={**body, "display_name": "Otro"}, headers=_headers(clinic, key)
        )
        stale = await client.patch(
            url,
            json={**body, "display_name": "Otro"},
            headers=_headers(clinic, f"off-{uuid4().hex}"),
        )
        foreign = await client.patch(
            f"/v1/operations/offerings/{other.offering_id}",
            json=body,
            headers=_headers(clinic, f"off-{uuid4().hex}"),
        )
    async with _client(e2e_session_factory, clinic, without_manage=True) as denied_client:
        denied = await denied_client.patch(
            url, json={**body, "expected_revision": 2}, headers=_headers(clinic, f"d-{uuid4()}")
        )

    assert first.status_code == 200, first.text
    assert first.json()["revision"] == 2 and first.json()["display_name"] == "Limpieza dental"
    assert replay.json() == first.json()
    assert reused.status_code == 409, reused.text
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "offering_revision_conflict"
    assert stale.json()["error"]["details"]["current_revision"] == 2
    assert foreign.status_code == 409
    assert foreign.json()["error"]["code"] == "catalog_configuration_conflict"
    assert denied.status_code == 403, denied.text
    row = e2e_admin_conn.execute(
        "SELECT display_name, revision FROM request_engine.offerings WHERE id = %s",
        (clinic.offering_id,),
    ).fetchone()
    assert row == ("Limpieza dental", 2)
    assert _scalar(
        e2e_admin_conn,
        "SELECT display_name <> 'Limpieza dental' FROM request_engine.offerings WHERE id = %s",
        other.offering_id,
    )
    versions = _scalar(
        e2e_admin_conn,
        "SELECT count(*) FROM request_engine.offering_versions WHERE offering_id = %s",
        clinic.offering_id,
    )
    assert versions == 1  # a rename never creates a version
    events = _outbox(e2e_admin_conn, clinic.offering_id, "catalog.offering_updated.v1")
    assert events == [{"offering_id": str(clinic.offering_id), "revision": 2}]


@pytest.mark.asyncio
async def test_supersession_appends_a_version_and_existing_reservation_keeps_its_terms(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = _world(e2e_admin_conn, "off-supersede")
    policy = {"slot_step_minutes": 15, "attendance": {"no_show_after_minutes": 20}}
    e2e_admin_conn.execute(
        "INSERT INTO request_engine.offering_version_booking_policies "
        "(organization_id, offering_version_id, revision, booking_policy) "
        "VALUES (%s, %s, 1, %s::jsonb)",
        (clinic.organization_id, clinic.offering_version_id, json.dumps(policy)),
    )
    url = f"/v1/operations/offerings/{clinic.offering_id}/versions"
    async with _client(e2e_session_factory, clinic) as client:
        slot = await first_slot(client, clinic)
        booked = await client.post(
            "/v1/appointments",
            json={"option_id": slot["option_id"], "subject_party_id": str(clinic.party_id)},
            headers=_headers(clinic, f"book-{uuid4().hex}"),
        )
        assert booked.status_code == 201, booked.text
        reservation_id = UUID(booked.json()["id"])
        before = e2e_admin_conn.execute(
            "SELECT offering_version_id, during, revision, booking_policy_snapshot "
            "FROM request_engine.reservations WHERE id = %s",
            (reservation_id,),
        ).fetchone()

        body = {
            "authority_party_id": str(clinic.party_id),
            "expected_current_offering_version_id": str(clinic.offering_version_id),
            "duration_minutes": 45,
            "booking_terms": {"amount": "4000.00", "currency": "DOP"},
        }
        key = f"sup-{uuid4().hex}"
        first = await client.post(url, json=body, headers=_headers(clinic, key))
        replay = await client.post(url, json=body, headers=_headers(clinic, key))
        stale = await client.post(url, json=body, headers=_headers(clinic, f"sup-{uuid4().hex}"))
        assert first.status_code == 201, first.text
        new_version = UUID(first.json()["offering_version_id"])
        price_only = await client.post(
            url,
            json={
                "authority_party_id": str(clinic.party_id),
                "expected_current_offering_version_id": str(new_version),
                "booking_terms": {"amount": 4200, "currency": "DOP"},
            },
            headers=_headers(clinic, f"sup-{uuid4().hex}"),
        )
        noop = await client.post(
            url,
            json={
                "authority_party_id": str(clinic.party_id),
                "expected_current_offering_version_id": price_only.json()["offering_version_id"],
                "duration_minutes": 45,
            },
            headers=_headers(clinic, f"sup-{uuid4().hex}"),
        )
        empty = await client.post(
            url,
            json={
                "authority_party_id": str(clinic.party_id),
                "expected_current_offering_version_id": str(new_version),
            },
            headers=_headers(clinic, f"sup-{uuid4().hex}"),
        )
        float_price = await client.post(
            url,
            json={**body, "booking_terms": {"amount": 19.9, "currency": "DOP"}},
            headers=_headers(clinic, f"sup-{uuid4().hex}"),
        )
        latest = await client.get(
            f"/v1/catalog/offerings/{clinic.offering_id}/configuration",
            params={"authority_party_id": str(clinic.party_id)},
            headers=_headers(clinic),
        )

    receipt = first.json()
    assert receipt["version"] == 2
    assert receipt["previous_offering_version_id"] == str(clinic.offering_version_id)
    assert receipt["duration_minutes"] == 45 and receipt["requirement_count"] == 1
    assert receipt["booking_terms"]["amount"] == "4000.00"
    assert replay.json() == receipt
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "offering_version_superseded"
    assert stale.json()["error"]["details"]["current_offering_version_id"] == str(new_version)
    assert price_only.status_code == 201, price_only.text
    assert price_only.json()["version"] == 3 and price_only.json()["duration_minutes"] == 45
    assert noop.status_code == 422, noop.text
    assert empty.status_code == 422, empty.text
    assert float_price.status_code == 422, float_price.text
    assert latest.json()["offering_version_id"] == price_only.json()["offering_version_id"]

    after = e2e_admin_conn.execute(
        "SELECT offering_version_id, during, revision, booking_policy_snapshot "
        "FROM request_engine.reservations WHERE id = %s",
        (reservation_id,),
    ).fetchone()
    assert after == before and after is not None
    assert after[0] == clinic.offering_version_id
    old = e2e_admin_conn.execute(
        "SELECT v.duration_minutes, t.amount FROM request_engine.offering_versions v "
        "JOIN request_engine.offering_version_booking_terms t ON t.offering_version_id = v.id "
        "WHERE v.id = %s",
        (clinic.offering_version_id,),
    ).fetchall()
    assert [(row[0], str(row[1])) for row in old] == [(30, "3500.000000")]
    new = e2e_admin_conn.execute(
        "SELECT v.version, v.duration_minutes, v.bookable, v.requestable, v.booking_policy, "
        "t.amount, t.currency FROM request_engine.offering_versions v "
        "JOIN request_engine.offering_version_booking_terms t ON t.offering_version_id = v.id "
        "WHERE v.id = %s",
        (new_version,),
    ).fetchone()
    assert new is not None
    assert new[:4] == (2, 45, True, True)
    assert new[4] == policy  # the effective (ledger) policy, not the bootstrap one
    assert (str(new[5]), new[6]) == ("4000.000000", "DOP")
    requirements = e2e_admin_conn.execute(
        "SELECT offering_version_id, capability_id, ordinal, quantity "
        "FROM request_engine.offering_resource_requirements "
        "WHERE offering_version_id IN (%s, %s) ORDER BY created_at",
        (clinic.offering_version_id, new_version),
    ).fetchall()
    assert [row[1:] for row in requirements[:1]] == [row[1:] for row in requirements[1:]]
    events = _outbox(e2e_admin_conn, clinic.offering_id, "catalog.offering_version_superseded.v1")
    assert len(events) == 2
    assert set(events[0]) == {
        "offering_id",
        "offering_version_id",
        "previous_offering_version_id",
        "version",
    }


async def _wait_for_blocked(observer: PgConnection, blocker_pid: int, count: int) -> None:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        rows = observer.execute(
            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock' "
            "AND query LIKE %s",
            ("%FROM request_engine.offerings%FOR UPDATE%",),
        ).fetchall()
        # PostgreSQL queues the second waiter behind the first tuple-lock waiter, so
        # the chain (barrier <- first <- second) is the deterministic "both wait" state.
        waiters = {cast(int, pid): set(cast(list[int], blockers)) for pid, blockers in rows}
        chained = [
            pid for pid, blockers in waiters.items() if blockers & ({blocker_pid} | set(waiters))
        ]
        direct = any(blocker_pid in blockers for blockers in waiters.values())
        if direct and len(chained) >= count:
            return
        await asyncio.sleep(0.025)
    seen = observer.execute(
        "SELECT pid, state, wait_event_type, pg_blocking_pids(pid), left(query, 200) "
        "FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"
    ).fetchall()
    raise AssertionError(f"supersessions did not wait on the Offering root: {seen}")


@pytest.mark.asyncio
async def test_concurrent_supersessions_create_exactly_one_version(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: psycopg.Connection[Any],
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = _world(e2e_admin_conn, "off-race")
    url = f"/v1/operations/offerings/{clinic.offering_id}/versions"

    def body(minutes: int) -> dict[str, object]:
        return {
            "authority_party_id": str(clinic.party_id),
            "expected_current_offering_version_id": str(clinic.offering_version_id),
            "duration_minutes": minutes,
        }

    blocker_row = e2e_barrier_conn.execute("SELECT pg_backend_pid()").fetchone()
    assert blocker_row is not None
    blocker_pid = cast(int, blocker_row[0])
    e2e_barrier_conn.execute(
        "SELECT id FROM request_engine.offerings WHERE id = %s FOR UPDATE", (clinic.offering_id,)
    )
    async with _client(e2e_session_factory, clinic) as client:
        first = asyncio.create_task(
            client.post(url, json=body(40), headers=_headers(clinic, f"r-{uuid4().hex}"))
        )
        second = asyncio.create_task(
            client.post(url, json=body(50), headers=_headers(clinic, f"r-{uuid4().hex}"))
        )
        try:
            await _wait_for_blocked(e2e_admin_conn, blocker_pid, 2)
            assert not first.done() and not second.done()
        finally:
            e2e_barrier_conn.rollback()
        results = await asyncio.gather(first, second)

    assert sorted(result.status_code for result in results) == [201, 409], [
        result.text for result in results
    ]
    loser = next(result for result in results if result.status_code == 409)
    assert loser.json()["error"]["code"] == "offering_version_superseded"
    versions = e2e_admin_conn.execute(
        "SELECT version FROM request_engine.offering_versions WHERE offering_id = %s "
        "ORDER BY version",
        (clinic.offering_id,),
    ).fetchall()
    assert versions == [(1,), (2,)]


@pytest.mark.asyncio
async def test_hours_exceptions_are_listed_with_ids_and_deactivated_not_deleted(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = _world(e2e_admin_conn, "exc")
    other = _world(e2e_admin_conn, "exc-other")
    params = {"authority_party_id": str(clinic.party_id)}
    list_url = f"/v1/catalog/locations/{clinic.location_id}/hours-exceptions"
    async with _client(e2e_session_factory, clinic, other) as client:
        initial = await client.get(list_url, params=params, headers=_headers(clinic))
        assert initial.status_code == 200, initial.text
        revision = initial.json()["operational_revision"]
        created = await client.put(
            f"/v1/operations/locations/{clinic.location_id}/hours-exceptions",
            json={
                "authority_party_id": str(clinic.party_id),
                "expected_operational_revision": revision,
                "start_at": datetime(2030, 2, 1, 12, tzinfo=UTC).isoformat(),
                "end_at": datetime(2030, 2, 1, 16, tzinfo=UTC).isoformat(),
                "exception_kind": "unavailable",
                "reason": "Fumigación",
            },
            headers=_headers(clinic, f"exc-{uuid4().hex}"),
        )
        assert created.status_code == 200, created.text
        exception_id = created.json()["exception_id"]
        listed = await client.get(list_url, params=params, headers=_headers(clinic))
        current = listed.json()["operational_revision"]
        deactivate_url = (
            f"/v1/operations/locations/{clinic.location_id}"
            f"/hours-exceptions/{exception_id}:deactivate"
        )
        stale = await client.post(
            deactivate_url,
            json={"authority_party_id": str(clinic.party_id), "expected_operational_revision": 1},
            headers=_headers(clinic, f"d-{uuid4().hex}"),
        )
        key = f"d-{uuid4().hex}"
        deactivate_body = {
            "authority_party_id": str(clinic.party_id),
            "expected_operational_revision": current,
        }
        done = await client.post(
            deactivate_url, json=deactivate_body, headers=_headers(clinic, key)
        )
        replay = await client.post(
            deactivate_url, json=deactivate_body, headers=_headers(clinic, key)
        )
        again = await client.post(
            deactivate_url,
            json={**deactivate_body, "expected_operational_revision": current + 1},
            headers=_headers(clinic, f"d-{uuid4().hex}"),
        )
        active_only = await client.get(list_url, params=params, headers=_headers(clinic))
        everything = await client.get(
            list_url, params={**params, "include_inactive": "true"}, headers=_headers(clinic)
        )
        foreign_list = await client.get(
            f"/v1/catalog/locations/{other.location_id}/hours-exceptions",
            params=params,
            headers=_headers(clinic),
        )
        foreign_deactivate = await client.post(
            f"/v1/operations/locations/{other.location_id}"
            f"/hours-exceptions/{exception_id}:deactivate",
            json=deactivate_body,
            headers=_headers(clinic, f"d-{uuid4().hex}"),
        )
        unknown_filter = await client.get(
            list_url, params={**params, "kind": "x"}, headers=_headers(clinic)
        )

    items = listed.json()["items"]
    assert [item["exception_id"] for item in items] == [exception_id]
    assert items[0]["reason"] == "Fumigación" and items[0]["active"] is True
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "location_operational_revision_conflict"
    assert done.status_code == 200, done.text
    assert done.json()["active"] is False
    assert done.json()["operational_revision"] == current + 1
    assert replay.json() == done.json()
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "catalog_configuration_conflict"
    assert active_only.json()["items"] == []
    assert active_only.json()["operational_revision"] == current + 1
    assert [item["active"] for item in everything.json()["items"]] == [False]
    assert foreign_list.status_code == 404
    assert foreign_deactivate.status_code == 409
    assert unknown_filter.status_code == 422
    row = e2e_admin_conn.execute(
        "SELECT active FROM request_engine.location_hours_exceptions WHERE id = %s",
        (UUID(exception_id),),
    ).fetchone()
    assert row == (False,)  # deactivated, never deleted
    events = _outbox(
        e2e_admin_conn, clinic.location_id, "catalog.location_hours_exception_deactivated.v1"
    )
    assert len(events) == 1 and "Fumigación" not in json.dumps(events)


@pytest.mark.asyncio
async def test_holiday_removal_deactivates_only_the_named_full_days(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = _world(e2e_admin_conn, "hol")
    second_location = cast(
        UUID,
        _scalar(
            e2e_admin_conn,
            "INSERT INTO request_engine.locations "
            "(organization_id, location_key, display_name, timezone) "
            "VALUES (%s, %s, 'Sede Madrid', 'Europe/Madrid') RETURNING id",
            clinic.organization_id,
            f"madrid-{uuid4().hex}",
        ),
    )
    kept, removed, never = date(2030, 12, 24), date(2030, 12, 25), date(2030, 12, 31)
    async with _client(e2e_session_factory, clinic) as client:
        declared = await client.put(
            "/v1/operations/organization/holidays",
            json={
                "authority_party_id": str(clinic.party_id),
                "holidays": [
                    {"date": kept.isoformat(), "reason": "Nochebuena"},
                    {"date": removed.isoformat(), "reason": "Navidad"},
                ],
            },
            headers=_headers(clinic, f"h-{uuid4().hex}"),
        )
        assert declared.status_code == 200, declared.text
        assert declared.json()["exceptions_created"] == 4
        body = {
            "authority_party_id": str(clinic.party_id),
            "dates": [removed.isoformat(), never.isoformat()],
        }
        key = f"hr-{uuid4().hex}"
        first = await client.post(
            "/v1/operations/organization/holidays:remove", json=body, headers=_headers(clinic, key)
        )
        replay = await client.post(
            "/v1/operations/organization/holidays:remove", json=body, headers=_headers(clinic, key)
        )
        duplicate = await client.post(
            "/v1/operations/organization/holidays:remove",
            json={**body, "dates": [removed.isoformat(), removed.isoformat()]},
            headers=_headers(clinic, f"hr-{uuid4().hex}"),
        )

    assert first.status_code == 200, first.text
    assert first.json() == {
        "dates": [removed.isoformat(), never.isoformat()],
        "locations_examined": 2,
        "exceptions_deactivated": 2,
        "dates_not_found": [never.isoformat()],
    }
    assert replay.json() == first.json()
    assert duplicate.status_code == 422
    rows = e2e_admin_conn.execute(
        "SELECT location_id, reason, active FROM request_engine.location_hours_exceptions "
        "WHERE organization_id = %s ORDER BY location_id, lower(during)",
        (clinic.organization_id,),
    ).fetchall()
    assert len(rows) == 4
    by_reason = {(row[0], row[1]): row[2] for row in rows}
    for location in (clinic.location_id, second_location):
        assert by_reason[(location, "Nochebuena")] is True
        assert by_reason[(location, "Navidad")] is False
    events = _outbox(
        e2e_admin_conn, clinic.organization_id, "catalog.organization_holidays_removed.v1"
    )
    assert events == [
        {"dates": [removed.isoformat(), never.isoformat()], "exceptions_deactivated": 2}
    ]
