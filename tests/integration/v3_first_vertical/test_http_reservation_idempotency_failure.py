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


async def _slot_options(
    client: httpx.AsyncClient,
    fixture: OperationsFixture,
) -> list[dict[str, object]]:
    response = await client.get(
        "/v1/appointments/slots",
        params={
            "offering_version_id": str(fixture.offering_version_id),
            "location_id": str(fixture.location_id),
            "window_start": datetime(2026, 8, 17, 13, 0, tzinfo=UTC).isoformat(),
            "window_end": datetime(2026, 8, 17, 16, 0, tzinfo=UTC).isoformat(),
        },
        headers={"Authorization": "Bearer agent"},
    )
    assert response.status_code == 200
    return cast(list[dict[str, object]], response.json())


async def _book(
    client: httpx.AsyncClient,
    fixture: OperationsFixture,
    *,
    option_id: str,
) -> dict[str, object]:
    response = await client.post(
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
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_booking_cancel_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        options = await _slot_options(client, fixture)
        reservation = await _book(
            client,
            fixture,
            option_id=cast(str, options[0]["option_id"]),
        )

    reservation_id = UUID(cast(str, reservation["id"]))
    revision = cast(int, reservation["revision"])
    path = f"/v1/appointments/{reservation_id}/cancel"
    key = f"lost-booking-cancel-{uuid4().hex}"
    body = {"expected_revision": revision, "reason": "response lost"}
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
    assert replay.json()["status"] == "cancelled"
    assert replay.json()["revision"] == revision + 1
    stored = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone()
    assert stored == ("cancelled", revision + 1)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reservation.cancelled.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_booking_reschedule_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        options = await _slot_options(client, fixture)
        assert len(options) >= 2
        reservation = await _book(
            client,
            fixture,
            option_id=cast(str, options[0]["option_id"]),
        )

    reservation_id = UUID(cast(str, reservation["id"]))
    revision = cast(int, reservation["revision"])
    target = options[1]
    path = f"/v1/appointments/{reservation_id}/reschedule"
    key = f"lost-reschedule-{uuid4().hex}"
    body = {
        "option_id": cast(str, target["option_id"]),
        "expected_revision": revision,
    }
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
    assert replay.json()["revision"] == revision + 1
    assert replay.json()["start_at"] == target["start_at"]
    active_claims = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
          AND status = 'active'
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone()
    assert active_claims == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reservation.rescheduled.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)
