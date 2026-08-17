# pyright: reportPrivateUsage=false

from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from ._response_loss import DropFirstMatchingResponseTransport
from .test_http_operations import (
    _FULL_CAPABILITIES,
    BearerTestActorResolver,
    OperationsFixture,
    _create_fixture,
)

PgConnection = Connection[Any]

_BOOKING_CAPABILITIES = _FULL_CAPABILITIES | frozenset({"appointments.confirm_attendance"})


def _app(session_factory: SessionFactory, fixture: OperationsFixture) -> FastAPI:
    actor = ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_BOOKING_CAPABILITIES,
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver({"agent": actor}),
    )


async def _book(client: httpx.AsyncClient, fixture: OperationsFixture) -> dict[str, object]:
    slots = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(fixture.offering_version_id),
            "location_id": str(fixture.location_id),
            "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2026, 8, 17, 16, 0, tzinfo=UTC).isoformat(),
        },
        headers={"Authorization": "Bearer agent"},
    )
    assert slots.status_code == 200
    option_id = cast(str, slots.json()[0]["option_id"])
    booked = await client.post(
        "/v1/appointments",
        json={
            "option_id": option_id,
            "subject_party_id": str(fixture.subject_party_id),
        },
        headers={
            "Authorization": "Bearer agent",
            "Idempotency-Key": f"prepare-book-{uuid4().hex}",
        },
    )
    assert booked.status_code == 201
    return cast(dict[str, object], booked.json())


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_attendance_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        reservation = await _book(client, fixture)

    reservation_id = UUID(cast(str, reservation["id"]))
    revision = cast(int, reservation["revision"])
    path = f"/v1/appointments/{reservation_id}/attendance"
    key = f"lost-attendance-{uuid4().hex}"
    body = {"response": "accepted", "expected_revision": revision}
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {"Authorization": "Bearer agent", "Idempotency-Key": key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(path, json=body, headers=headers)
        replay = await client.post(path, json=body, headers=headers)

    assert replay.status_code == 200
    assert replay.json()["response_status"] == "accepted"
    assert replay.json()["reservation_revision"] == revision + 1
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.attendance_responses
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reservation.attendance_response_recorded.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_attendance_same_key_different_response_is_idempotency_conflict(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    key = f"attendance-conflict-{uuid4().hex}"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        reservation = await _book(client, fixture)
        reservation_id = UUID(cast(str, reservation["id"]))
        revision = cast(int, reservation["revision"])
        path = f"/v1/appointments/{reservation_id}/attendance"
        headers = {"Authorization": "Bearer agent", "Idempotency-Key": key}
        accepted = await client.post(
            path,
            json={"response": "accepted", "expected_revision": revision},
            headers=headers,
        )
        conflicting = await client.post(
            path,
            json={"response": "declined", "expected_revision": revision},
            headers=headers,
        )

    assert accepted.status_code == 200
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "idempotency_conflict"
    scopes = admin_conn.execute(
        """
        SELECT capability, count(*)
        FROM request_engine.idempotency_records
        WHERE organization_id = %s
          AND principal_id = %s
          AND idempotency_key = %s
        GROUP BY capability
        """,
        (fixture.organization_id, fixture.principal_id, key),
    ).fetchall()
    assert scopes == [("booking.record_attendance_response", 1)]
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.attendance_responses
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)
