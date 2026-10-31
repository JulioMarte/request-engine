"""Closing and reopening a ServiceQueue (``queue_service_queue_set_active``).

Protected risks (plausible regressions that must turn this red):

* a queue closed while subjects are still waiting/called/serving (silent drain);
* a closed queue still admitting walk-ins or joins;
* the close not serializing with admission on the ServiceQueue row, so an entry
  committed while the close waited is not counted;
* the revision CAS or unchanged-state refusal missing (lost update);
* replay creating a second transition, or a reused key with a different body
  accepted;
* a foreign tenant closing another organization's queue, or a caller without
  ``queue.configure`` or without the exact ``operations.manage_supply``
  representation succeeding;
* reopening a queue whose Location is inactive;
* the audit/outbox change fact missing or carrying more than identifiers.

Execution boundary: the real HTTP application and the least-privilege runtime role
on PostgreSQL 18. Oracles: authoritative ``service_queues``, ``queue_entries``,
``audit_records`` and ``outbox_messages`` rows read with the admin connection.
"""

import asyncio
import time
from dataclasses import replace
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .operational_support import PgConnection
from .tenant_sandbox import (
    ALL_PUBLIC_CAPABILITIES,
    TenantSandbox,
    auth,
    client_with_actors,
    seed_tenant_sandbox,
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.postgres,
    pytest.mark.e2e,
    pytest.mark.contract,
    pytest.mark.invariant,
    pytest.mark.adversarial,
]

_STAFF = ALL_PUBLIC_CAPABILITIES | {"queue.configure", "queue.check_in"}


def _actor(sandbox: TenantSandbox, capabilities: frozenset[str] = _STAFF) -> ActorContext:
    return ActorContext(sandbox.organization_id, sandbox.principal_id, capabilities)


def _key(label: str) -> str:
    return f"queue-set-active-{label}-{uuid4().hex}"


def _grant_supply_authority(conn: PgConnection, sandbox: TenantSandbox) -> None:
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


def _queue_row(conn: PgConnection, queue_id: UUID) -> tuple[bool, int]:
    row = conn.execute(
        "SELECT active, revision FROM request_engine.service_queues WHERE id = %s",
        (queue_id,),
    ).fetchone()
    assert row is not None
    return cast(bool, row[0]), cast(int, row[1])


def _entry_count(conn: PgConnection, queue_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.queue_entries WHERE service_queue_id = %s",
        (queue_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _facts(conn: PgConnection, queue_id: UUID) -> list[tuple[str, dict[str, Any]]]:
    rows = conn.execute(
        "SELECT event_type, payload FROM request_engine.outbox_messages "
        "WHERE aggregate_kind = 'ServiceQueue' AND aggregate_id = %s ORDER BY created_at, id",
        (queue_id,),
    ).fetchall()
    return [(cast(str, row[0]), cast(dict[str, Any], row[1])) for row in rows]


def _audit_count(conn: PgConnection, queue_id: UUID) -> int:
    row = conn.execute(
        "SELECT count(*) FROM request_engine.audit_records "
        "WHERE aggregate_kind = 'ServiceQueue' AND aggregate_id = %s "
        "AND command_name = 'queue.set_service_queue_active'",
        (queue_id,),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _seed_entry(conn: PgConnection, sandbox: TenantSandbox, status: str = "waiting") -> None:
    called = "at - interval '1 minute'" if status in ("called", "serving") else "NULL"
    conn.execute(
        "WITH transition AS (SELECT clock_timestamp() AS at) "
        "INSERT INTO request_engine.queue_entries "
        "(organization_id, service_queue_id, subject_party_id, status, "
        "arrived_at, admitted_at, called_at) "
        f"SELECT %s, %s, %s, %s, at - interval '2 minutes', at - interval '2 minutes', {called} "
        "FROM transition",
        (sandbox.organization_id, sandbox.queue_id, sandbox.party_id, status),
    )


async def _set_active(
    client: httpx.AsyncClient,
    sandbox: TenantSandbox,
    *,
    active: bool,
    revision: int,
    key: str | None = None,
    queue_id: UUID | None = None,
    party_id: UUID | None = None,
) -> httpx.Response:
    return await client.post(
        f"/v1/queues/{queue_id or sandbox.queue_id}:set-active",
        json={
            "authority_party_id": str(party_id or sandbox.party_id),
            "expected_revision": revision,
            "active": active,
        },
        headers=auth(sandbox, idempotency_key=key or _key("set")),
    )


async def _walk_in(client: httpx.AsyncClient, sandbox: TenantSandbox) -> httpx.Response:
    return await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=_key("check-in")),
    )


def _code(response: httpx.Response) -> str:
    return cast(str, response.json()["error"]["code"])


async def test_close_reopen_replay_and_conflicts(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "queue-close")
    _grant_supply_authority(e2e_admin_conn, clinic)
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        stale = await _set_active(client, clinic, active=False, revision=7)
        assert stale.status_code == 409, stale.text
        assert _code(stale) == "service_queue_revision_conflict"
        assert stale.json()["error"]["details"]["current_revision"] == 1
        unchanged = await _set_active(client, clinic, active=True, revision=1)
        assert unchanged.status_code == 409 and _code(unchanged) == "service_queue_state_unchanged"

        key = _key("close")
        closed = await _set_active(client, clinic, active=False, revision=1, key=key)
        assert closed.status_code == 200, closed.text
        assert closed.json() == {
            "queue_id": str(clinic.queue_id),
            "queue_key": closed.json()["queue_key"],
            "display_name": closed.json()["display_name"],
            "location_id": str(clinic.location_id),
            "offering_id": str(clinic.offering_id),
            "active": False,
            "revision": 2,
        }
        assert _queue_row(e2e_admin_conn, clinic.queue_id) == (False, 2)

        replay = await _set_active(client, clinic, active=False, revision=1, key=key)
        assert replay.status_code == 200 and replay.json() == closed.json()
        reused = await _set_active(client, clinic, active=True, revision=1, key=key)
        assert reused.status_code == 409, reused.text
        assert _queue_row(e2e_admin_conn, clinic.queue_id) == (False, 2)

        refused = await _walk_in(client, clinic)
        assert refused.status_code == 409 and _code(refused) == "queue_inactive", refused.text
        assert _entry_count(e2e_admin_conn, clinic.queue_id) == 0

        reopened = await _set_active(client, clinic, active=True, revision=2)
        assert reopened.status_code == 200 and reopened.json()["revision"] == 3
        admitted = await _walk_in(client, clinic)
        assert admitted.status_code == 201, admitted.text

    assert [event for event, _ in _facts(e2e_admin_conn, clinic.queue_id)] == [
        "service_queue.deactivated.v1",
        "service_queue.activated.v1",
    ]
    for _, payload in _facts(e2e_admin_conn, clinic.queue_id):
        assert set(payload) == {"queue_id", "location_id", "active", "revision"}
    assert _audit_count(e2e_admin_conn, clinic.queue_id) == 2


@pytest.mark.parametrize("status", ["waiting", "called", "serving"])
async def test_close_refused_while_entries_are_active(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory, status: str
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "queue-close-busy")
    _grant_supply_authority(e2e_admin_conn, clinic)
    _seed_entry(e2e_admin_conn, clinic, status)
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        refused = await _set_active(client, clinic, active=False, revision=1)
    assert refused.status_code == 409, refused.text
    error = refused.json()["error"]
    assert error["code"] == "service_queue_has_active_entries"
    assert error["details"][status] == 1
    assert sum(error["details"][name] for name in ("waiting", "called", "serving")) == 1
    assert _queue_row(e2e_admin_conn, clinic.queue_id) == (True, 1)
    assert _facts(e2e_admin_conn, clinic.queue_id) == []
    assert _audit_count(e2e_admin_conn, clinic.queue_id) == 0


async def test_terminal_entries_do_not_block_and_inactive_location_blocks_reopen(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "queue-close-terminal")
    _grant_supply_authority(e2e_admin_conn, clinic)
    _seed_entry(e2e_admin_conn, clinic, "waiting")
    e2e_admin_conn.execute(
        "UPDATE request_engine.queue_entries SET status = 'cancelled' WHERE service_queue_id = %s",
        (clinic.queue_id,),
    )
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        closed = await _set_active(client, clinic, active=False, revision=1)
        assert closed.status_code == 200, closed.text
        e2e_admin_conn.execute(
            "UPDATE request_engine.locations SET active = false WHERE id = %s",
            (clinic.location_id,),
        )
        reopen = await _set_active(client, clinic, active=True, revision=2)
    assert reopen.status_code == 409 and _code(reopen) == "queue_configuration_conflict"
    assert _queue_row(e2e_admin_conn, clinic.queue_id) == (False, 2)


async def test_authority_capability_and_tenant_opacity(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "queue-close-owner")
    other = seed_tenant_sandbox(e2e_admin_conn, "queue-close-foreign")
    _grant_supply_authority(e2e_admin_conn, clinic)
    _grant_supply_authority(e2e_admin_conn, other)
    denied = replace(clinic, token=f"token-denied-{uuid4().hex}")
    no_party = seed_tenant_sandbox(e2e_admin_conn, "queue-close-no-authority")
    actors = {
        clinic.token: _actor(clinic),
        other.token: _actor(other),
        denied.token: _actor(clinic, _STAFF - {"queue.configure"}),
        no_party.token: _actor(no_party),
    }
    async with client_with_actors(e2e_session_factory, actors) as client:
        foreign = await _set_active(
            client, other, active=False, revision=1, queue_id=clinic.queue_id
        )
        forbidden = await _set_active(client, denied, active=False, revision=1)
        unrepresented = await _set_active(client, no_party, active=False, revision=1)
    assert foreign.status_code == 404 and _code(foreign) == "queue_not_found", foreign.text
    assert forbidden.status_code == 403, forbidden.text
    assert unrepresented.status_code in (403, 409), unrepresented.text
    assert _queue_row(e2e_admin_conn, clinic.queue_id) == (True, 1)
    assert _queue_row(e2e_admin_conn, no_party.queue_id) == (True, 1)


async def _wait_blocked_by(observer: PgConnection, blocker_pid: int, fragment: str) -> int:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        rows = observer.execute(
            "SELECT pid, pg_blocking_pids(pid) FROM pg_stat_activity "
            "WHERE datname = current_database() AND wait_event_type = 'Lock' "
            "AND query ILIKE %s",
            (f"%{fragment}%",),
        ).fetchall()
        for pid, blockers in rows:
            if blocker_pid in blockers:
                return int(pid)
        await asyncio.sleep(0.02)
    raise AssertionError(f"no backend running {fragment!r} was blocked by {blocker_pid}")


def _blocker_pid(barrier: PgConnection) -> int:
    row = barrier.execute("SELECT pg_backend_pid()").fetchone()
    assert row is not None
    return cast(int, row[0])


async def test_close_waits_on_queue_root_and_counts_admission_committed_meanwhile(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "queue-close-race")
    _grant_supply_authority(e2e_admin_conn, clinic)
    blocker = _blocker_pid(e2e_barrier_conn)
    e2e_barrier_conn.execute(
        "SELECT 1 FROM request_engine.service_queues WHERE id = %s FOR UPDATE",
        (clinic.queue_id,),
    )
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        close = asyncio.create_task(_set_active(client, clinic, active=False, revision=1))
        await _wait_blocked_by(e2e_admin_conn, blocker, "service_queues")
        # The admission that holds the queue root commits an entry while the close waits.
        e2e_barrier_conn.execute(
            "WITH transition AS (SELECT clock_timestamp() AS at) "
            "INSERT INTO request_engine.queue_entries "
            "(organization_id, service_queue_id, subject_party_id, arrived_at, admitted_at) "
            "SELECT %s, %s, %s, at, at FROM transition",
            (clinic.organization_id, clinic.queue_id, clinic.party_id),
        )
        e2e_barrier_conn.commit()
        refused = await close
    assert refused.status_code == 409, refused.text
    assert _code(refused) == "service_queue_has_active_entries"
    assert _queue_row(e2e_admin_conn, clinic.queue_id) == (True, 1)


async def test_concurrent_close_and_walk_in_serialize_on_the_queue_row(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "queue-close-walk-in")
    _grant_supply_authority(e2e_admin_conn, clinic)
    blocker = _blocker_pid(e2e_barrier_conn)
    e2e_barrier_conn.execute(
        "SELECT 1 FROM request_engine.service_queues WHERE id = %s FOR UPDATE",
        (clinic.queue_id,),
    )
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        close = asyncio.create_task(_set_active(client, clinic, active=False, revision=1))
        first = await _wait_blocked_by(e2e_admin_conn, blocker, "service_queues")
        walk_in = asyncio.create_task(_walk_in(client, clinic))
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            row = e2e_admin_conn.execute(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                "AND wait_event_type = 'Lock' AND pid <> %s AND query ILIKE %s",
                (first, "%service_queues%"),
            ).fetchone()
            if row is not None and cast(int, row[0]) >= 1:
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("walk-in never queued behind the ServiceQueue row lock")
        e2e_barrier_conn.rollback()
        closed, admitted = await asyncio.gather(close, walk_in)
    active, revision = _queue_row(e2e_admin_conn, clinic.queue_id)
    entries = _entry_count(e2e_admin_conn, clinic.queue_id)
    if closed.status_code == 200:
        assert admitted.status_code == 409 and _code(admitted) == "queue_inactive"
        assert (active, revision, entries) == (False, 2, 0)
    else:
        assert admitted.status_code == 201, admitted.text
        assert _code(closed) == "service_queue_has_active_entries"
        assert (active, revision, entries) == (True, 1, 1)
