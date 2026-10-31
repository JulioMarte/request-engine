"""Walk-in join and triage actions now signal the change feed (ADR 0020).

Protected risk: ``queue.join``, ``queue.skip``, ``queue.recall_hold`` and
``queue.release_recall_hold`` committed their facts without an outbox event, so
a client subscribed to ``queue``/``day_board`` never learned that its queue view
was stale. Each now appends a versioned ``queue.*`` fact in the same
transaction, and the routing table maps it to ``queue`` (plus ``day_board``
when the QueueEntry is linked to a Reservation).

Plausible regressions caught: any of the four commands losing its outbox append
(the expected ``change`` never arrives and the stream times out), an event
emitted under the wrong aggregate (the feed drops it), a reserved entry not
reaching ``day_board`` or a walk-in leaking onto it, the recall-hold free-text
reason copied into the outbox payload, or personal data in the stream.

Execution boundary: uvicorn serving ``create_app`` over TCP; every command and
the LISTEN run as the least-privilege app role on PostgreSQL 18. Oracles: the
sequential order of the HTTP commands and the authoritative outbox rows read
with the admin connection.
"""

from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest

from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .change_feed_support import (
    DATA_FIELDS,
    PHONE,
    STREAM,
    Sse,
    book,
    check_in,
    event_data,
    feed_actor,
    feed_app,
    seed_phone,
    serve,
)
from .operational_support import PgConnection
from .tenant_sandbox import TenantSandbox, auth, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract, pytest.mark.security]

_HOLD_REASON = "Paciente espera a su hija Maria antes de pasar"
_TRIAGE_CAPABILITIES = frozenset(
    {"queue.join", "queue.skip", "queue.recall_hold", "queue.release_recall_hold"}
)


def _actor(sandbox: TenantSandbox) -> ActorContext:
    base = feed_actor(sandbox)
    return ActorContext(
        base.organization_id, base.principal_id, base.capabilities | _TRIAGE_CAPABILITIES
    )


def _walk_in_queue(conn: PgConnection, sandbox: TenantSandbox) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.service_queues "
        "(organization_id, location_id, offering_id, queue_key, display_name) "
        "VALUES (%s, %s, %s, %s, 'Walk-in desk') RETURNING id",
        (
            sandbox.organization_id,
            sandbox.location_id,
            sandbox.offering_id,
            f"walk-in-{uuid4().hex}",
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _post(
    client: httpx.AsyncClient, sandbox: TenantSandbox, path: str, body: dict[str, object]
) -> dict[str, Any]:
    response = await client.post(
        path, json=body, headers=auth(sandbox, idempotency_key=f"triage-feed-{uuid4().hex}")
    )
    assert response.status_code in {200, 201}, response.text
    return cast(dict[str, Any], response.json())


async def _changes(sse: Sse, count: int) -> list[dict[str, Any]]:
    return [event_data(await sse.event()) for _ in range(count)]


@pytest.mark.asyncio
async def test_walk_in_join_and_triage_actions_produce_pii_free_change_events(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "triage-feed")
    party_name = seed_phone(e2e_admin_conn, clinic)
    walk_in_queue = _walk_in_queue(e2e_admin_conn, clinic)
    app = feed_app(e2e_session_factory, {clinic.token: _actor(clinic)})
    async with serve(app) as client:
        reservation = await book(client, clinic)
        async with client.stream(
            "GET", STREAM, params={"topics": "queue,day_board"}, headers=auth(clinic)
        ) as response:
            assert response.status_code == 200
            sse = Sse(response)
            assert await sse.block() == {"retry": "3000"}

            # Walk-in: queue only, never day_board (no Reservation is linked).
            joined = await _post(
                client,
                clinic,
                f"/v1/queues/{walk_in_queue}/join",
                {"subject_party_id": str(clinic.party_id)},
            )
            (join_event,) = await _changes(sse, 1)
            assert set(join_event) == DATA_FIELDS
            assert (join_event["topic"], join_event["kind"]) == ("queue", "queue.entry_joined.v1")
            assert join_event["resource_type"] == "queue_entry"
            assert join_event["resource_id"] == joined["id"]
            assert join_event["scope"]["queue_id"] == str(walk_in_queue)

            # Reserved entry: every triage fact reaches day_board and queue.
            entry = await check_in(client, clinic, reservation["id"])
            assert [e["kind"] for e in await _changes(sse, 2)] == ["queue.entry_checked_in.v1"] * 2
            base = f"/v1/queue-entries/{entry['id']}"
            held = await _post(
                client,
                clinic,
                f"{base}/recall-hold",
                {
                    "condition_kind": "until_customer_initiates",
                    "expected_revision": entry["revision"],
                    "reason": _HOLD_REASON,
                },
            )
            held_events = await _changes(sse, 2)
            released = await _post(
                client,
                clinic,
                f"{base}/recall-hold/release",
                {"hold_id": held["hold"]["id"], "expected_revision": held["revision"]},
            )
            released_events = await _changes(sse, 2)
            await _post(
                client,
                clinic,
                f"{base}/skip",
                {"reason": "no_response", "expected_revision": released["revision"]},
            )
            skipped_events = await _changes(sse, 2)
            raw_stream = "\n".join(sse.raw)

    for events, kind in (
        (held_events, "queue.entry_recall_held.v1"),
        (released_events, "queue.entry_recall_released.v1"),
        (skipped_events, "queue.entry_skipped.v1"),
    ):
        assert [(e["topic"], e["kind"]) for e in events] == [("day_board", kind), ("queue", kind)]
        for event in events:
            assert set(event) == DATA_FIELDS
            assert event["resource_type"] == "queue_entry"
            assert event["resource_id"] == entry["id"]
            assert event["scope"]["queue_id"] == str(clinic.queue_id)

    for forbidden in (party_name, PHONE, str(clinic.party_id), _HOLD_REASON):
        assert forbidden not in raw_stream

    # Oracle: exactly one durable fact per command, in command order, on the
    # QueueEntry aggregate, and the free-text hold reason is not in any payload.
    rows = e2e_admin_conn.execute(
        "SELECT event_type, aggregate_kind, aggregate_id, payload::text "
        "FROM request_engine.outbox_messages "
        "WHERE organization_id = %s AND event_type IN ("
        "'queue.entry_joined.v1','queue.entry_recall_held.v1',"
        "'queue.entry_recall_released.v1','queue.entry_skipped.v1') "
        "ORDER BY created_at",
        (clinic.organization_id,),
    ).fetchall()
    assert [(row[0], row[1], str(row[2])) for row in rows] == [
        ("queue.entry_joined.v1", "QueueEntry", joined["id"]),
        ("queue.entry_recall_held.v1", "QueueEntry", entry["id"]),
        ("queue.entry_recall_released.v1", "QueueEntry", entry["id"]),
        ("queue.entry_skipped.v1", "QueueEntry", entry["id"]),
    ]
    assert all(_HOLD_REASON not in row[3] for row in rows)
