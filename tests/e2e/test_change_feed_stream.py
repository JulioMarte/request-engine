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

import asyncio
import json
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import httpx
import pytest
import uvicorn
from fastapi import FastAPI

from request_engine.entrypoints.http.app import create_app
from request_engine.platform.changes.feed import ChangeFeed, ChangeFeedSettings
from request_engine.platform.changes.model import FeedSnapshot
from request_engine.platform.db.session import SessionFactory, tenant_transaction
from request_engine.platform.outbox.postgres import append_outbox
from request_engine.platform.security.context import ActorContext

from .f3_acceptance_assertions import acceptance_actor
from .operational_support import PgConnection
from .tenant_sandbox import SandboxResolver, TenantSandbox, auth, seed_tenant_sandbox

pytestmark = [pytest.mark.postgres, pytest.mark.e2e, pytest.mark.contract, pytest.mark.security]

_SIGNING_KEY = b"request-engine-e2e-change-feed-key"
_STREAM = "/v1/changes/stream"
_DATA_FIELDS = {"topic", "kind", "resource_type", "resource_id", "scope", "occurred_at"}
_PHONE = "+18095550147"


def _actor(sandbox: TenantSandbox) -> ActorContext:
    base = acceptance_actor(sandbox)
    return ActorContext(
        base.organization_id,
        base.principal_id,
        base.capabilities | {"appointments.day_board", "queue.staff_read"},
    )


@asynccontextmanager
async def _serve(app: FastAPI) -> AsyncGenerator[httpx.AsyncClient]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="warning"))
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        async with asyncio.timeout(10):
            while not server.started:  # noqa: ASYNC110 - uvicorn exposes only a flag
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=httpx.Timeout(20.0)
        ) as client:
            yield client
    finally:
        server.should_exit = True
        await task
        sock.close()


class _Sse:
    def __init__(self, response: httpx.Response) -> None:
        self._lines = response.aiter_lines()
        self.raw: list[str] = []

    async def block(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        async with asyncio.timeout(15):
            while True:
                line = await anext(self._lines)
                self.raw.append(line)
                if line == "":
                    if fields:
                        return fields
                    continue
                key, _, value = line.partition(":")
                fields[key] = value.removeprefix(" ")

    async def event(self) -> dict[str, str]:
        while True:
            fields = await self.block()
            if fields.get("event") != "heartbeat":
                return fields


def _data(fields: dict[str, str]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(fields["data"]))


async def _book(client: httpx.AsyncClient, sandbox: TenantSandbox) -> dict[str, Any]:
    slots = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(sandbox.offering_version_id),
            "location_id": str(sandbox.location_id),
            "window_start": datetime(2030, 1, 7, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2030, 1, 7, 16, 0, tzinfo=UTC).isoformat(),
        },
        headers=auth(sandbox),
    )
    assert slots.status_code == 200, slots.text
    booked = await client.post(
        "/v1/appointments",
        json={"option_id": slots.json()[0]["option_id"], "subject_party_id": str(sandbox.party_id)},
        headers=auth(sandbox, idempotency_key=f"feed-book-{uuid4().hex}"),
    )
    assert booked.status_code == 201, booked.text
    return cast(dict[str, Any], booked.json())


async def _check_in(
    client: httpx.AsyncClient, sandbox: TenantSandbox, reservation_id: str
) -> dict[str, Any]:
    checked_in = await client.post(
        f"/v1/queues/{sandbox.queue_id}/check-in",
        json={"subject_party_id": str(sandbox.party_id), "reservation_id": reservation_id},
        headers=auth(sandbox, idempotency_key=f"feed-check-in-{uuid4().hex}"),
    )
    assert checked_in.status_code == 201, checked_in.text
    return cast(dict[str, Any], checked_in.json())


def _feed(app: FastAPI) -> ChangeFeed:
    return cast(ChangeFeed, app.state.change_feed)


async def _until(predicate: Any) -> None:
    async with asyncio.timeout(10):
        while not predicate():  # noqa: ASYNC110 - bounded poll of server-side state
            await asyncio.sleep(0.02)


def _app(
    session_factory: SessionFactory,
    actors: dict[str, ActorContext],
    settings: ChangeFeedSettings | None = None,
) -> FastAPI:
    return create_app(
        session_factory=session_factory,
        actor_resolver=SandboxResolver(actors),
        appointment_option_signing_key=_SIGNING_KEY,
        change_feed_settings=settings or ChangeFeedSettings(),
    )


def _seed_phone(conn: PgConnection, sandbox: TenantSandbox) -> str:
    conn.execute(
        "INSERT INTO request_engine.party_contact_points "
        "(organization_id, party_id, channel, normalized_value, source_kind) "
        "VALUES (%s, %s, 'phone', %s, 'operator')",
        (sandbox.organization_id, sandbox.party_id, _PHONE),
    )
    row = conn.execute(
        "SELECT display_name FROM request_engine.parties WHERE id = %s", (sandbox.party_id,)
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


@pytest.mark.asyncio
async def test_day_board_stream_is_commit_only_pii_free_tenant_isolated_and_replayable(
    e2e_admin_conn: PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    clinic = seed_tenant_sandbox(e2e_admin_conn, "feed")
    other = seed_tenant_sandbox(e2e_admin_conn, "feed-other")
    party_name = _seed_phone(e2e_admin_conn, clinic)
    app = _app(e2e_session_factory, {clinic.token: _actor(clinic), other.token: _actor(other)})
    async with _serve(app) as client:
        async with client.stream(
            "GET", _STREAM, params={"topics": "day_board"}, headers=auth(clinic)
        ) as response:
            assert response.status_code == 200
            assert response.headers["content-type"].startswith("text/event-stream")
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-accel-buffering"] == "no"
            sse = _Sse(response)
            assert await sse.block() == {"retry": "3000"}

            # The other tenant commits first; if it leaked it would arrive first.
            await _book(client, other)
            reservation = await _book(client, clinic)
            created = await sse.event()
            assert created["event"] == "change" and created["id"]
            created_data = _data(created)
            assert set(created_data) == _DATA_FIELDS
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

            entry = await _check_in(client, clinic, reservation["id"])
            checked_in = _data(await sse.event())
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
            assert _data(called_event)["kind"] == "queue.entry_called.v1"
            cursor = called_event["id"]
            raw_stream = "\n".join(sse.raw)

        for forbidden in (party_name, _PHONE, str(clinic.party_id), str(other.organization_id)):
            assert forbidden not in raw_stream
        await _until(lambda: _feed(app).hub.stream_count() == 0)

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
            "GET", _STREAM, params={"topics": "day_board"}, headers=headers
        ) as response:
            assert response.status_code == 200
            sse = _Sse(response)
            assert await sse.block() == {"retry": "3000"}
            first, second = await sse.event(), await sse.event()
            last_cursor = second["id"]
        assert [_data(first)["kind"], _data(second)["kind"]] == [
            "service_session.started.v1",
            "service_session.completed.v1",
        ]
        assert {_data(first)["resource_id"], _data(second)["resource_id"]} == {started.json()["id"]}
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
        await _until(lambda: _feed(app).hub.stream_count() == 0)

        # Nothing was missed after the last replayed cursor: the next event is new.
        await _book(client, other)
        async with client.stream(
            "GET",
            _STREAM,
            params={"topics": "day_board"},
            headers={**auth(clinic), "Last-Event-ID": last_cursor},
        ) as response:
            sse = _Sse(response)
            await sse.block()
            fresh = await _book(client, clinic)
            assert _data(await sse.event())["resource_id"] == fresh["id"]

        too_old = FeedSnapshot(
            snapshot="3:3:", taken_at=datetime.now(UTC) - timedelta(days=1)
        ).cursor()
        for unknown in ("not-a-cursor", too_old):
            async with client.stream(
                "GET",
                _STREAM,
                params={"topics": "day_board"},
                headers={**auth(clinic), "Last-Event-ID": unknown},
            ) as response:
                sse = _Sse(response)
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
    actors = {clinic.token: _actor(clinic), "board-only": board_only, "nothing": nothing}
    app = _app(e2e_session_factory, actors, ChangeFeedSettings(max_streams_per_principal=2))
    feed = _feed(app)
    async with _serve(app) as client:
        board_headers = {"Authorization": "Bearer board-only"}
        denied = await client.get(
            _STREAM, params={"topics": "day_board,requests"}, headers=board_headers
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["details"] == {"capability": "requests.read_inbox"}
        none = await client.get(_STREAM, headers={"Authorization": "Bearer nothing"})
        assert none.status_code == 403
        unknown = await client.get(_STREAM, params={"topics": "billing"}, headers=board_headers)
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "unknown_change_topic"
        unauthenticated = await client.get(_STREAM)
        assert unauthenticated.status_code == 401
        assert feed.hub.stream_count() == 0

        # Omitted topics -> exactly the authorized ones (here: day_board only).
        async with client.stream("GET", _STREAM, headers=board_headers) as first:
            assert first.status_code == 200
            await _until(lambda: feed.hub.stream_count(board_only.principal_id) == 1)
            async with client.stream("GET", _STREAM, headers=board_headers) as second:
                assert second.status_code == 200
                await _until(lambda: feed.hub.stream_count(board_only.principal_id) == 2)
                over = await client.get(_STREAM, headers=board_headers)
                assert over.status_code == 429
                assert over.headers["retry-after"] == "10"
                assert over.json()["error"]["code"] == "change_stream_limit_exceeded"
                # Another principal of the same organization is unaffected.
                async with client.stream("GET", _STREAM, headers=auth(clinic)) as own:
                    assert own.status_code == 200
        # Closing streams releases their slots (no leak on disconnect).
        await _until(lambda: feed.hub.stream_count() == 0)
        async with client.stream("GET", _STREAM, headers=board_headers) as again:
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
    app = _app(e2e_session_factory, {clinic.token: _actor(clinic)}, settings)
    async with _serve(app) as client:
        down = await client.get(_STREAM, headers=auth(clinic))
        assert down.status_code == 503
        assert down.headers["retry-after"] == "5"
        assert down.json()["error"]["code"] == "change_feed_unavailable"
        assert _feed(app).hub.stream_count() == 0
        business = await client.get("/v1/capabilities", headers=auth(clinic))
        assert business.status_code == 200
