"""``GET /v1/changes/stream`` over a real HTTP server, real LISTEN and PostgreSQL 18.

Protected guarantees (ADR 0020, request-engine-app ``docs/contracts/changes-stream.md``):

- only committed owner facts produce ``change`` events; a rolled-back transaction
  produces none (NOTIFY and the fact are both transactional);
- the ``data`` is exactly the contract field set and carries no personal or
  business payload (no party name, phone or party id);
- one organization never receives another organization's changes;
- ``Last-Event-ID`` replays the facts missed while disconnected, in commit
  order; an unknown or too-old cursor yields ``reset``;
- authorization is per topic with existing read capabilities and fails closed
  (403, no subscription), the per-principal concurrent limit answers 429, an
  unknown topic 422, and an unavailable LISTEN 503 without breaking the app.

Plausible regressions caught: notifying before commit or for rollbacks, leaking
payload fields, missing tenant filter in the replay read or fan-out, an
"id > n" cursor ordering, silently narrowing unauthorized topics, leaking stream
slots on disconnect. Execution boundary: uvicorn serving ``create_app`` over
TCP, the least-privilege app role for every runtime query and the LISTEN.
Oracles: authoritative rows read with the admin connection and the order of the
sequential HTTP commands.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest

from request_engine.platform.changes.feed import ChangeFeedSettings
from request_engine.platform.changes.model import FeedSnapshot
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.security.context import ActorContext

from .change_feed_support import (
    DATA_FIELDS,
    PHONE,
    STREAM,
    Sse,
    book,
    change_feed,
    check_in,
    event_data,
    feed_actor,
    feed_app,
    seed_phone,
    serve,
    until,
)
from .operational_support import PgConnection
from .tenant_sandbox import auth, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract, pytest.mark.security]


@pytest.mark.asyncio
async def test_day_board_stream_is_commit_only_pii_free_tenant_isolated_and_replayable(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "feed")
    other = seed_tenant_sandbox(e2e_admin_conn, "feed-other")
    party_name = seed_phone(e2e_admin_conn, clinic)
    app = feed_app(
        e2e_session_factory, {clinic.token: feed_actor(clinic), other.token: feed_actor(other)}
    )
    async with serve(app) as client:
        async with client.stream(
            "GET", STREAM, params={"topics": "day_board"}, headers=auth(clinic)
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-accel-buffering"] == "no"
            sse = Sse(response)
            assert await sse.block() == {"retry": "3000"}

            # The other tenant commits first; if it leaked it would arrive first.
            await book(client, other)
            reservation = await book(client, clinic)
            created = await sse.event()
            assert created["event"] == "change" and created["id"]
            created_data = event_data(created)
            assert set(created_data) == DATA_FIELDS
            assert set(created_data["scope"]) == {"queue_id", "location_id", "business_date"}
            assert created_data["topic"] == "day_board"
            assert created_data["kind"] == "reservation.created.v1"
            assert created_data["resource_type"] == "reservation"
            assert created_data["resource_id"] == reservation["id"]
            fact = e2e_admin_conn.execute(
                "SELECT lower(r.during), l.timezone, o.occurred_at "
                "FROM request_engine.reservations r "
                "JOIN request_engine.locations l ON l.id = r.location_id "
                "JOIN request_engine.outbox_messages o ON o.aggregate_id = r.id "
                "WHERE r.id = %s AND o.event_type = 'reservation.created.v1'",
                (UUID(reservation["id"]),),
            ).fetchone()
            assert fact is not None
            start, timezone, occurred_at = fact
            assert created_data["scope"] == {
                "queue_id": None,
                "location_id": str(clinic.location_id),
                "business_date": start.astimezone(ZoneInfo(timezone)).date().isoformat(),
            }
            assert created_data["occurred_at"] == occurred_at.astimezone(UTC).isoformat(
                timespec="milliseconds"
            ).replace("+00:00", "Z")

            entry = await check_in(client, clinic, reservation["id"])
            checked_in = event_data(await sse.event())
            assert (checked_in["kind"], checked_in["resource_type"]) == (
                "queue.entry_checked_in.v1",
                "queue_entry",
            )
            assert checked_in["resource_id"] == entry["id"]
            assert checked_in["scope"]["queue_id"] == str(clinic.queue_id)

            # A rolled-back fact (same append primitive, same app role) emits nothing:
            # the next event is the committed call-next that follows it.
            with pytest.raises(RuntimeError, match="roll back"):
                async with tenant_transaction(e2e_session_factory, clinic.organization_id) as tx:
                    await append_outbox(
                        tx,
                        organization_id=clinic.organization_id,
                        event_type="reservation.cancelled.v1",
                        aggregate_kind="Reservation",
                        aggregate_id=UUID(reservation["id"]),
                        payload={"reservation_id": reservation["id"]},
                    )
                    raise RuntimeError("roll back")
            called = await client.post(
                f"/v1/queues/{clinic.queue_id}/call-next",
                headers=auth(clinic, idempotency_key=f"feed-call-{uuid4().hex}"),
            )
            assert called.status_code == 200, called.text
            called_event = await sse.event()
            assert event_data(called_event)["kind"] == "queue.entry_called.v1"
            cursor = called_event["id"]
            raw_stream = "\n".join(sse.raw)

        for forbidden in (party_name, PHONE, str(clinic.party_id), str(other.organization_id)):
            assert forbidden not in raw_stream
        await until(lambda: change_feed(app).hub.stream_count() == 0)

        # Missed while disconnected: start then complete the service, sequentially.
        started = await client.post(
            f"/v1/queue-entries/{entry['id']}/service/start",
            json={
                "resource_id": str(clinic.resource_id),
                "location_id": str(clinic.location_id),
                "expected_queue_revision": called.json()["revision"],
            },
            headers=auth(clinic, idempotency_key=f"feed-start-{uuid4().hex}"),
        )
        assert started.status_code == 201, started.text
        completed = await client.post(
            f"/v1/service-sessions/{started.json()['id']}/complete",
            json={"expected_revision": started.json()["revision"]},
            headers=auth(clinic, idempotency_key=f"feed-complete-{uuid4().hex}"),
        )
        assert completed.status_code == 200, completed.text

        headers = {**auth(clinic), "Last-Event-ID": cursor}
        async with client.stream(
            "GET", STREAM, params={"topics": "day_board"}, headers=headers
        ) as response:
            assert response.status_code == 200
            sse = Sse(response)
            assert await sse.block() == {"retry": "3000"}
            first, second = await sse.event(), await sse.event()
            last_cursor = second["id"]
        assert [event_data(first)["kind"], event_data(second)["kind"]] == [
            "service_session.started.v1",
            "service_session.completed.v1",
        ]
        assert {event_data(first)["resource_id"], event_data(second)["resource_id"]} == {
            started.json()["id"]
        }
        # Oracle: the authoritative facts exist in exactly that commit sequence.
        order = e2e_admin_conn.execute(
            "SELECT event_type FROM request_engine.outbox_messages "
            "WHERE organization_id = %s AND aggregate_id = %s ORDER BY created_at",
            (clinic.organization_id, UUID(started.json()["id"])),
        ).fetchall()
        assert [row[0] for row in order] == [
            "service_session.started.v1",
            "service_session.completed.v1",
        ]
        await until(lambda: change_feed(app).hub.stream_count() == 0)

        # Nothing was missed after the last replayed cursor: the next event is new.
        await book(client, other)
        async with client.stream(
            "GET",
            STREAM,
            params={"topics": "day_board"},
            headers={**auth(clinic), "Last-Event-ID": last_cursor},
        ) as response:
            sse = Sse(response)
            await sse.block()
            fresh = await book(client, clinic)
            assert event_data(await sse.event())["resource_id"] == fresh["id"]

        too_old = FeedSnapshot(
            snapshot="3:3:", taken_at=datetime.now(UTC) - timedelta(days=1)
        ).cursor()
        for unknown in ("not-a-cursor", too_old):
            async with client.stream(
                "GET",
                STREAM,
                params={"topics": "day_board"},
                headers={**auth(clinic), "Last-Event-ID": unknown},
            ) as response:
                sse = Sse(response)
                await sse.block()
                assert await sse.event() == {"event": "reset", "data": "{}"}


@pytest.mark.asyncio
async def test_stream_admission_fails_closed_and_is_bounded(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "feed-admission")
    board_only = ActorContext(
        clinic.organization_id, uuid4(), frozenset({"appointments.day_board"})
    )
    nothing = ActorContext(clinic.organization_id, uuid4(), frozenset({"business.get_info"}))
    actors = {clinic.token: feed_actor(clinic), "board-only": board_only, "nothing": nothing}
    app = feed_app(e2e_session_factory, actors, ChangeFeedSettings(max_streams_per_principal=2))
    feed = change_feed(app)
    async with serve(app) as client:
        board_headers = {"Authorization": "Bearer board-only"}
        denied = await client.get(
            STREAM, params={"topics": "day_board,requests"}, headers=board_headers
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["details"] == {"capability": "requests.read_inbox"}
        none = await client.get(STREAM, headers={"Authorization": "Bearer nothing"})
        assert none.status_code == 403
        unknown = await client.get(STREAM, params={"topics": "billing"}, headers=board_headers)
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "unknown_change_topic"
        unauthenticated = await client.get(STREAM)
        assert unauthenticated.status_code == 401
        assert feed.hub.stream_count() == 0

        # Omitted topics -> exactly the authorized ones (here: day_board only).
        async with client.stream("GET", STREAM, headers=board_headers) as first:
            assert first.status_code == 200
            await until(lambda: feed.hub.stream_count(board_only.principal_id) == 1)
            async with client.stream("GET", STREAM, headers=board_headers) as second:
                assert second.status_code == 200
                await until(lambda: feed.hub.stream_count(board_only.principal_id) == 2)
                over = await client.get(STREAM, headers=board_headers)
                assert over.status_code == 429
                assert over.headers["retry-after"] == "10"
                assert over.json()["error"]["code"] == "change_stream_limit_exceeded"
                # Another principal of the same organization is unaffected.
                async with client.stream("GET", STREAM, headers=auth(clinic)) as own:
                    assert own.status_code == 200
        # Closing streams releases their slots (no leak on disconnect).
        await until(lambda: feed.hub.stream_count() == 0)
        async with client.stream("GET", STREAM, headers=board_headers) as again:
            assert again.status_code == 200


@pytest.mark.asyncio
async def test_unavailable_listen_answers_503_and_leaves_the_app_serving(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "feed-down")
    settings = ChangeFeedSettings(
        listen_dsn="postgresql://nobody:nothing@127.0.0.1:1/none", startup_wait_seconds=0.5
    )
    app = feed_app(e2e_session_factory, {clinic.token: feed_actor(clinic)}, settings)
    async with serve(app) as client:
        down = await client.get(STREAM, headers=auth(clinic))
        assert down.status_code == 503
        assert down.headers["retry-after"] == "5"
        assert down.json()["error"]["code"] == "change_feed_unavailable"
        assert change_feed(app).hub.stream_count() == 0
        business = await client.get("/v1/capabilities", headers=auth(clinic))
        assert business.status_code == 200
