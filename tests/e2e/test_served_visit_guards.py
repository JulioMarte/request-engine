"""A served visit closes its Reservation to re-admission, cancellation and reschedule.

Protected guarantee: INV-SERVED-VISIT-001. Defects this replaces (verified live
before the fix): ``queue.check_in`` admitted a Reservation whose visit had
already completed (only ``status='confirmed'`` and "no ACTIVE entry of the same
subject in the same queue" were checked), ``queue.join`` accepted the same
Reservation with no check at all, and ``booking.cancel_reservation`` /
``booking.reschedule_reservation`` released or moved the capacity of a visit
that had already been served.

Plausible regressions each test must catch:

- the check-in guard removed or scoped to the same queue only (second queue
  re-admits the served reservation);
- the guard over-broad (a reservation whose entry merely left the queue can no
  longer be checked in again);
- cancel/reschedule/join losing the served check (capacity claims released or
  moved, Reservation revision bumped, a ``reservation.cancelled.v1`` fact);
- the cancel guard reading without ``FOR SHARE`` (a cancel racing an in-flight
  service completion commits after the visit was served);
- two concurrent check-ins of one Reservation both committing.

Execution boundary: owner HTTP operations on the real runtime and the
least-privilege app role on PostgreSQL 18; races use an independent barrier
connection and ``pg_blocking_pids`` synchronization, never sleeps as ordering.
Oracles: authoritative reservations, capacity_claims, queue_entries and
outbox_messages rows read with the admin connection.
"""

import asyncio
import time
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .front_desk_recall_support import FRONT_DESK_CAPABILITIES
from .operational_support import PgConnection
from .tenant_sandbox import (
    ALL_PUBLIC_CAPABILITIES,
    TenantSandbox,
    auth,
    client_with_actors,
    first_slot,
    seed_tenant_sandbox,
)

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.invariant]

_STAFF_CAPABILITIES = frozenset(
    {
        "queue.join",
        "queue.leave",
        "queue.call_next",
        "service_session.start",
        "service_session.complete",
        "appointments.cancel",
        "appointments.reschedule",
    }
)


def _actor(sandbox: TenantSandbox) -> ActorContext:
    return ActorContext(
        sandbox.organization_id,
        sandbox.principal_id,
        ALL_PUBLIC_CAPABILITIES | FRONT_DESK_CAPABILITIES | _STAFF_CAPABILITIES,
    )


def _key(label: str) -> str:
    return f"served-guard-{label}-{uuid4().hex}"


def _second_queue(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.service_queues "
        "(organization_id, location_id, offering_id, queue_key, display_name) "
        "VALUES (%s, %s, %s, %s, 'Second operational stage') RETURNING id",
        (sandbox.organization_id, sandbox.location_id, sandbox.offering_id, f"s2-{uuid4().hex}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _slots(client: httpx.AsyncClient, sandbox: TenantSandbox) -> list[dict[str, Any]]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": "2030-01-07T13:00:00+00:00",
            "window_end": "2030-01-07T16:00:00+00:00",
        },
        headers=auth(sandbox),
    )
    assert response.status_code == 200, response.text
    slots = cast(list[dict[str, Any]], response.json())
    assert len(slots) >= 2, slots
    return slots


async def _book(client: httpx.AsyncClient, sandbox: TenantSandbox, option_id: str) -> Any:
    booked = await client.post(
        "/v1/appointments",
        json={"option_id": option_id, "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=_key("book")),
    )
    assert booked.status_code == 201, booked.text
    return booked.json()


async def _check_in(
    client: httpx.AsyncClient, sandbox: TenantSandbox, queue_id: UUID, reservation_id: str
) -> httpx.Response:
    return await client.post(
        f"/v1/queues/{queue_id}/check-in",
        json={"subject_party_id": str(sandbox.party_id), "reservation_id": reservation_id},
        headers=auth(sandbox, idempotency_key=_key("check-in")),
    )


async def _start_service(
    client: httpx.AsyncClient, sandbox: TenantSandbox, entry_id: str
) -> dict[str, Any]:
    called = await client.post(
        f"/v1/queues/{sandbox.queue_id}/call-next",
        headers=auth(sandbox, idempotency_key=_key("call")),
    )
    assert called.status_code == 200 and called.json()["id"] == entry_id, called.text
    started = await client.post(
        f"/v1/queue-entries/{entry_id}/service/start",
        json={
            "resource_id": str(sandbox.resource_id),
            "location_id": str(sandbox.location_id),
            "expected_queue_revision": called.json()["revision"],
        },
        headers=auth(sandbox, idempotency_key=_key("start")),
    )
    assert started.status_code == 201, started.text
    return cast(dict[str, Any], started.json())


async def _complete(
    client: httpx.AsyncClient, sandbox: TenantSandbox, session: dict[str, Any]
) -> httpx.Response:
    return await client.post(
        f"/v1/service-sessions/{session['id']}/complete",
        json={"expected_revision": session["revision"]},
        headers=auth(sandbox, idempotency_key=_key("complete")),
    )


async def _cancel(
    client: httpx.AsyncClient, sandbox: TenantSandbox, reservation: dict[str, Any]
) -> httpx.Response:
    return await client.post(
        f"/v1/appointments/{reservation['id']}/cancel",
        json={"expected_revision": reservation["revision"], "reason": "patient left"},
        headers=auth(sandbox, idempotency_key=_key("cancel")),
    )


def _reservation_state(conn: PgConnection, reservation_id: str) -> tuple[str, int, int]:
    row = conn.execute(
        "SELECT r.status, r.revision, "
        "(SELECT count(*) FROM request_engine.capacity_claims c "
        " WHERE c.reservation_id = r.id AND c.status = 'active') "
        "FROM request_engine.reservations r WHERE r.id = %s",
        (UUID(reservation_id),),
    ).fetchone()
    assert row is not None
    return cast(str, row[0]), cast(int, row[1]), cast(int, row[2])


def _entries(conn: PgConnection, reservation_id: str) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT service_queue_id::text, status FROM request_engine.queue_entries "
        "WHERE reservation_id = %s ORDER BY admitted_at, id",
        (UUID(reservation_id),),
    ).fetchall()
    return [(cast(str, row[0]), cast(str, row[1])) for row in rows]


def _lifecycle_facts(conn: PgConnection, reservation_id: str) -> list[str]:
    rows = conn.execute(
        "SELECT event_type FROM request_engine.outbox_messages "
        "WHERE aggregate_id = %s AND event_type IN "
        "('reservation.cancelled.v1', 'reservation.rescheduled.v1')",
        (UUID(reservation_id),),
    ).fetchall()
    return [cast(str, row[0]) for row in rows]


def _assert_conflict(response: httpx.Response, code: str) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == code, response.text


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


@pytest.mark.asyncio
async def test_served_reservation_cannot_be_readmitted_cancelled_or_rescheduled(
    e2e_admin_conn: PgConnection, e2e_session_factory: SessionFactory
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "served-guard")
    second_queue = _second_queue(e2e_admin_conn, clinic)
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        slots = await _slots(client, clinic)
        reservation = await _book(client, clinic, slots[0]["option_id"])

        # Negative control: leaving the queue is not a served visit, so the same
        # reservation may be checked in again (the guard is not over-broad).
        first = await _check_in(client, clinic, clinic.queue_id, reservation["id"])
        assert first.status_code == 201, first.text
        left = await client.post(
            f"/v1/queues/{clinic.queue_id}/entries/{first.json()['id']}/leave",
            json={"expected_revision": first.json()["revision"], "reason": "stepped out"},
            headers=auth(clinic, idempotency_key=_key("leave")),
        )
        assert left.status_code == 200, left.text
        again = await _check_in(client, clinic, clinic.queue_id, reservation["id"])
        assert again.status_code == 201, again.text

        session = await _start_service(client, clinic, again.json()["id"])
        completed = await _complete(client, clinic, session)
        assert completed.status_code == 200, completed.text
        served_state = _reservation_state(e2e_admin_conn, reservation["id"])
        served_entries = _entries(e2e_admin_conn, reservation["id"])
        assert served_state[0] == "confirmed" and served_state[2] > 0
        assert [status for _, status in served_entries] == ["cancelled", "completed"]

        for queue_id in (clinic.queue_id, second_queue):
            _assert_conflict(
                await _check_in(client, clinic, queue_id, reservation["id"]),
                "reservation_already_served",
            )
        joined = await client.post(
            f"/v1/queues/{second_queue}/join",
            json={"subject_party_id": str(clinic.party_id), "reservation_id": reservation["id"]},
            headers=auth(clinic, idempotency_key=_key("join")),
        )
        _assert_conflict(joined, "reservation_already_served")
        _assert_conflict(await _cancel(client, clinic, reservation), "reservation_already_served")
        rescheduled = await client.post(
            f"/v1/appointments/{reservation['id']}/reschedule",
            json={"option_id": slots[1]["option_id"], "expected_revision": reservation["revision"]},
            headers=auth(clinic, idempotency_key=_key("reschedule")),
        )
        _assert_conflict(rescheduled, "reservation_already_served")

    # Nothing changed: same status, revision and active claims; no new entry;
    # no cancellation/reschedule fact.
    assert _reservation_state(e2e_admin_conn, reservation["id"]) == served_state
    assert _entries(e2e_admin_conn, reservation["id"]) == served_entries
    assert _lifecycle_facts(e2e_admin_conn, reservation["id"]) == []


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_concurrent_check_ins_of_one_reservation_admit_exactly_one_entry(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "served-guard-race-check-in")
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        reservation = await _book(client, clinic, (await first_slot(client, clinic))["option_id"])
        # Barrier: hold the queue serialization root so both admissions are in
        # flight (each in its own transaction/connection) before either decides.
        e2e_barrier_conn.execute(
            "SELECT 1 FROM request_engine.service_queues WHERE id = %s FOR UPDATE",
            (clinic.queue_id,),
        )
        tasks = [
            asyncio.create_task(_check_in(client, clinic, clinic.queue_id, reservation["id"]))
            for _ in range(2)
        ]
        try:
            deadline = time.monotonic() + 15.0
            waiting = 0
            while waiting < 2 and time.monotonic() < deadline:
                row = e2e_admin_conn.execute(
                    # The first admission waits on the barrier, the second queues
                    # behind the first on the same row lock.
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND cardinality(pg_blocking_pids(pid)) > 0 AND query ILIKE %s",
                    ("%FROM request_engine.service_queues%FOR UPDATE%",),
                ).fetchone()
                waiting = int(row[0]) if row is not None else 0
                await asyncio.sleep(0.02)
            assert waiting == 2, "both admissions must be in flight behind the barrier"
        finally:
            e2e_barrier_conn.rollback()
        responses = await asyncio.gather(*tasks)

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201, 409], [response.text for response in responses]
    loser = next(response for response in responses if response.status_code == 409)
    assert loser.json()["error"]["code"] == "already_in_queue"
    assert _entries(e2e_admin_conn, reservation["id"]) == [(str(clinic.queue_id), "waiting")]
    facts = e2e_admin_conn.execute(
        "SELECT count(*) FROM request_engine.outbox_messages "
        "WHERE organization_id = %s AND event_type = 'queue.entry_checked_in.v1'",
        (clinic.organization_id,),
    ).fetchone()
    assert facts is not None and facts[0] == 1


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_cancel_racing_an_in_flight_completion_waits_and_refuses_the_served_visit(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "served-guard-race-cancel")
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        reservation = await _book(client, clinic, (await first_slot(client, clinic))["option_id"])
        entry = await _check_in(client, clinic, clinic.queue_id, reservation["id"])
        assert entry.status_code == 201, entry.text
        session = await _start_service(client, clinic, entry.json()["id"])
        before = _reservation_state(e2e_admin_conn, reservation["id"])

        # Barrier on the Resource: completion locks queue -> entry -> resource,
        # so it stops holding the QueueEntry lock with the visit still serving.
        blocker_pid = e2e_barrier_conn.info.backend_pid
        e2e_barrier_conn.execute(
            "SELECT 1 FROM request_engine.resources WHERE id = %s FOR UPDATE",
            (clinic.resource_id,),
        )
        try:
            completing = asyncio.create_task(_complete(client, clinic, session))
            completion_pid = await _wait_blocked_by(e2e_admin_conn, blocker_pid, "resources")
            cancelling = asyncio.create_task(_cancel(client, clinic, reservation))
            # The cancel must wait for the completion (its served-visit read locks
            # the serving QueueEntry), not run ahead on a 'serving' snapshot.
            await _wait_blocked_by(e2e_admin_conn, completion_pid, "queue_entries")
        finally:
            e2e_barrier_conn.rollback()
        completed, cancelled = await asyncio.gather(completing, cancelling)

    assert completed.status_code == 200, completed.text
    _assert_conflict(cancelled, "reservation_already_served")
    assert _reservation_state(e2e_admin_conn, reservation["id"]) == before
    assert _entries(e2e_admin_conn, reservation["id"]) == [(str(clinic.queue_id), "completed")]
    assert _lifecycle_facts(e2e_admin_conn, reservation["id"]) == []


@pytest.mark.asyncio
@pytest.mark.concurrency
async def test_cancel_waits_for_an_in_flight_admission_of_the_same_reservation(
    e2e_admin_conn: PgConnection,
    e2e_barrier_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    """Admission holds the Reservation FOR SHARE until it commits.

    Regression caught: reading the Reservation without a lock lets a cancel
    commit between the admission's "confirmed" read and its insert, leaving a
    QueueEntry admitted for a Reservation cancelled before the admission
    committed.
    """
    clinic = seed_tenant_sandbox(e2e_admin_conn, "served-guard-race-admission")
    async with client_with_actors(e2e_session_factory, {clinic.token: _actor(clinic)}) as client:
        reservation = await _book(client, clinic, (await first_slot(client, clinic))["option_id"])
        # Barrier on the subject Party: the admission's QueueEntry insert takes a
        # FOR KEY SHARE foreign-key lock on it after the Reservation was read.
        blocker_pid = e2e_barrier_conn.info.backend_pid
        e2e_barrier_conn.execute(
            "SELECT 1 FROM request_engine.parties WHERE id = %s FOR UPDATE",
            (clinic.party_id,),
        )
        try:
            admitting = asyncio.create_task(
                _check_in(client, clinic, clinic.queue_id, reservation["id"])
            )
            admission_pid = await _wait_blocked_by(e2e_admin_conn, blocker_pid, "queue_entries")
            cancelling = asyncio.create_task(_cancel(client, clinic, reservation))
            await _wait_blocked_by(e2e_admin_conn, admission_pid, "reservations")
        finally:
            e2e_barrier_conn.rollback()
        admitted, cancelled = await asyncio.gather(admitting, cancelling)

    assert admitted.status_code == 201, admitted.text
    assert cancelled.status_code == 200, cancelled.text
    order = e2e_admin_conn.execute(
        "SELECT event_type FROM request_engine.outbox_messages WHERE organization_id = %s "
        "AND event_type IN ('queue.entry_checked_in.v1', 'reservation.cancelled.v1') "
        "ORDER BY change_xid::text::bigint",
        (clinic.organization_id,),
    ).fetchall()
    assert [row[0] for row in order] == ["queue.entry_checked_in.v1", "reservation.cancelled.v1"]
