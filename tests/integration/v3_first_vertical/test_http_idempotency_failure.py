# pyright: reportPrivateUsage=false

from typing import Any, cast
from uuid import uuid4

import httpx
import pytest
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from .test_http_operations import (
    _FULL_CAPABILITIES,
    BearerTestActorResolver,
    _create_fixture,
)

PgConnection = Connection[Any]


class _DropFirstBookingResponseTransport(httpx.AsyncBaseTransport):
    """Let the ASGI app finish, then simulate transport loss before the client sees the response."""

    def __init__(self, app: object) -> None:
        self._inner = httpx.ASGITransport(app=cast(Any, app))
        self._dropped = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self._inner.handle_async_request(request)
        if (
            not self._dropped
            and request.method == "POST"
            and request.url.path == "/v1/appointments"
        ):
            self._dropped = True
            await response.aclose()
            raise httpx.ReadError("simulated response loss after committed booking", request=request)
        return response

    async def aclose(self) -> None:
        await self._inner.aclose()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_r19_committed_booking_response_lost_then_same_key_retry_replays_one_effect(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_CAPABILITIES,
        )
    }
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver(actors),
    )
    auth = {"Authorization": "Bearer agent"}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as discovery_client:
        slots_response = await discovery_client.get(
            "/v1/appointments/slots",
            params={
                "offering_version_id": str(fixture.offering_version_id),
                "location_id": str(fixture.location_id),
                "window_start": "2026-08-17T13:00:00+00:00",
                "window_end": "2026-08-17T16:00:00+00:00",
            },
            headers=auth,
        )
    assert slots_response.status_code == 200
    option = slots_response.json()[0]

    idempotency_key = f"r19-lost-response-{uuid4().hex}"
    booking_body = {
        "option_id": option["option_id"],
        "subject_party_id": str(fixture.subject_party_id),
    }
    transport = _DropFirstBookingResponseTransport(app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(
                "/v1/appointments",
                json=booking_body,
                headers={**auth, "Idempotency-Key": idempotency_key},
            )

        # The transport exception happened only after the ASGI application completed the
        # request, so the authoritative transaction has already committed. The retry must
        # replay the completed idempotency record instead of acquiring capacity again.
        retry = await client.post(
            "/v1/appointments",
            json=booking_body,
            headers={**auth, "Idempotency-Key": idempotency_key},
        )

    assert retry.status_code == 201
    reservation_id = retry.json()["id"]
    reservation_rows = admin_conn.execute(
        """
        SELECT id, status, revision
        FROM request_engine.reservations
        WHERE organization_id = %s
          AND subject_party_id = %s
          AND offering_version_id = %s
        """,
        (
            fixture.organization_id,
            fixture.subject_party_id,
            fixture.offering_version_id,
        ),
    ).fetchall()
    assert reservation_rows == [(reservation_rows[0][0], "confirmed", 1)]
    assert str(reservation_rows[0][0]) == reservation_id

    claims = admin_conn.execute(
        """
        SELECT count(*), count(*) FILTER (WHERE status = 'active')
        FROM request_engine.capacity_claims
        WHERE organization_id = %s
          AND reservation_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone()
    assert claims == (1, 1)

    idempotency = admin_conn.execute(
        """
        SELECT status, result_data -> 'reservation' ->> 'id'
        FROM request_engine.idempotency_records
        WHERE organization_id = %s
          AND principal_id = %s
          AND capability = 'booking.book_appointment'
          AND idempotency_key = %s
        """,
        (fixture.organization_id, fixture.principal_id, idempotency_key),
    ).fetchone()
    assert idempotency == ("completed", reservation_id)

    outbox_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND aggregate_kind = 'Reservation'
          AND aggregate_id = %s
          AND event_type = 'reservation.created.v1'
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone()
    assert outbox_count == (1,)
