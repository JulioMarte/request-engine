# pyright: reportPrivateUsage=false

from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from psycopg import Connection

from request_engine.platform.db.session import SessionFactory
from tests.integration.v3_first_vertical._race_support import race_behind_row_lock
from tests.integration.v3_first_vertical.test_http_attendance_idempotency_failure import (
    _app as booking_app,
)
from tests.integration.v3_first_vertical.test_http_attendance_idempotency_failure import (
    _book,
)
from tests.integration.v3_first_vertical.test_http_operations import (
    _create_fixture as booking_fixture,
)
from tests.integration.v3_first_vertical.test_http_request_idempotency_failure import (
    _app as request_app,
)
from tests.integration.v3_first_vertical.test_http_requests import (
    _create_fixture as request_fixture,
)
from tests.integration.v3_first_vertical.test_http_reservation_idempotency_failure import (
    _slot_options,
)

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_request_cancel_same_revision_has_one_winner_and_one_revision_conflict(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = request_fixture(admin_conn)
    app = request_app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer agent"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as setup:
        created = await setup.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            json={
                "payload": {"message": "concurrent cancellation"},
                "requester_party_id": str(fixture.requester_party_id),
            },
            headers={**auth, "Idempotency-Key": f"race-request-{uuid4().hex}"},
        )
    assert created.status_code == 201
    request_id = UUID(cast(str, created.json()["request"]["id"]))
    revision = cast(int, created.json()["request"]["revision"])
    path = f"/v1/requests/{request_id}/cancel"
    body = {"expected_revision": revision, "reason": "concurrent cancel"}

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as first_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as second_client,
    ):
        first, second = await race_behind_row_lock(
            admin_conn,
            table="requests",
            organization_id=fixture.organization_id,
            aggregate_id=request_id,
            first=first_client.post(
                path,
                json=body,
                headers={**auth, "Idempotency-Key": f"request-a-{uuid4().hex}"},
            ),
            second=second_client.post(
                path,
                json=body,
                headers={**auth, "Idempotency-Key": f"request-b-{uuid4().hex}"},
            ),
        )

    typed = cast(list[httpx.Response], [first, second])
    assert all(isinstance(item, httpx.Response) for item in typed)
    assert sorted(item.status_code for item in typed) == [200, 409]
    loser = next(item for item in typed if item.status_code == 409)
    assert loser.json()["error"]["code"] == "revision_conflict"
    assert admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.requests
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, request_id),
    ).fetchone() == ("cancelled", revision + 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_reservation_cancel_vs_reschedule_same_revision_has_one_winner(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = booking_fixture(admin_conn)
    app = booking_app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer agent"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as setup:
        options = await _slot_options(setup, fixture)
        reservation = await _book(setup, fixture)
    assert len(options) >= 2
    reservation_id = UUID(cast(str, reservation["id"]))
    revision = cast(int, reservation["revision"])
    cancel_path = f"/v1/appointments/{reservation_id}/cancel"
    reschedule_path = f"/v1/appointments/{reservation_id}/reschedule"

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as first_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as second_client,
    ):
        first, second = await race_behind_row_lock(
            admin_conn,
            table="reservations",
            organization_id=fixture.organization_id,
            aggregate_id=reservation_id,
            first=first_client.post(
                cancel_path,
                json={"expected_revision": revision, "reason": "race"},
                headers={**auth, "Idempotency-Key": f"cancel-a-{uuid4().hex}"},
            ),
            second=second_client.post(
                reschedule_path,
                json={
                    "expected_revision": revision,
                    "option_id": cast(str, options[1]["option_id"]),
                },
                headers={**auth, "Idempotency-Key": f"reschedule-b-{uuid4().hex}"},
            ),
        )

    typed = cast(list[httpx.Response], [first, second])
    assert all(isinstance(item, httpx.Response) for item in typed)
    assert sorted(item.status_code for item in typed) == [200, 409]
    loser = next(item for item in typed if item.status_code == 409)
    assert loser.json()["error"]["code"] == "revision_conflict"
    stored = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone()
    assert stored is not None
    assert stored[1] == revision + 1
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
    assert active_claims == ((0,) if stored[0] == "cancelled" else (1,))


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_attendance_same_revision_has_one_winner_and_one_revision_conflict(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = booking_fixture(admin_conn)
    app = booking_app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer agent"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as setup:
        reservation = await _book(setup, fixture)
    reservation_id = UUID(cast(str, reservation["id"]))
    revision = cast(int, reservation["revision"])
    path = f"/v1/appointments/{reservation_id}/attendance"

    async with (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as first_client,
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as second_client,
    ):
        first, second = await race_behind_row_lock(
            admin_conn,
            table="reservations",
            organization_id=fixture.organization_id,
            aggregate_id=reservation_id,
            first=first_client.post(
                path,
                json={"response": "accepted", "expected_revision": revision},
                headers={**auth, "Idempotency-Key": f"attendance-a-{uuid4().hex}"},
            ),
            second=second_client.post(
                path,
                json={"response": "declined", "expected_revision": revision},
                headers={**auth, "Idempotency-Key": f"attendance-b-{uuid4().hex}"},
            ),
        )

    typed = cast(list[httpx.Response], [first, second])
    assert all(isinstance(item, httpx.Response) for item in typed)
    assert sorted(item.status_code for item in typed) == [200, 409]
    loser = next(item for item in typed if item.status_code == 409)
    assert loser.json()["error"]["code"] == "revision_conflict"
    assert admin_conn.execute(
        """
        SELECT revision
        FROM request_engine.reservations
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (revision + 1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.attendance_responses
        WHERE organization_id = %s AND reservation_id = %s
        """,
        (fixture.organization_id, reservation_id),
    ).fetchone() == (1,)
