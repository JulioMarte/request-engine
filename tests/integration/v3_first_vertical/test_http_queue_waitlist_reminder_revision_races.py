import httpx
import pytest
from psycopg import Connection
from typing import Any, cast
from uuid import UUID, uuid4

from request_engine.platform.db.session import SessionFactory

from ._race_support import race_behind_row_lock
from .test_http_queue_idempotency_failure import _app as queue_app, _join
from .test_http_waitlist_idempotency_failure import _app as waitlist_app
from .test_http_waitlist import _fixture as waitlist_fixture
from .test_http_reminder_idempotency_failure import _app as reminder_app, _create_body
from .test_communications_reminders import _create_fixture as reminder_fixture
from .test_http_operations import _create_fixture as queue_fixture

PgConnection = Connection[Any]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_queue_leave_same_revision_has_one_winner_and_one_revision_conflict(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = queue_fixture(admin_conn)
    app = queue_app(app_session_factory, fixture)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as setup:
        entry = await _join(setup, fixture, key=f"race-join-{uuid4().hex}")
    entry_id = UUID(cast(str, entry["id"]))
    revision = cast(int, entry["revision"])
    path = f"/v1/queues/{fixture.queue_id}/entries/{entry_id}/leave"
    body = {"expected_revision": revision, "reason": "concurrent leave"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as first_client, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as second_client:
        first, second = await race_behind_row_lock(
            admin_conn,
            table="queue_entries",
            organization_id=fixture.organization_id,
            aggregate_id=entry_id,
            first=first_client.post(path, json=body, headers={"Authorization": "Bearer agent", "Idempotency-Key": f"leave-a-{uuid4().hex}"}),
            second=second_client.post(path, json=body, headers={"Authorization": "Bearer agent", "Idempotency-Key": f"leave-b-{uuid4().hex}"}),
        )

    responses = [first, second]
    assert all(isinstance(item, httpx.Response) for item in responses)
    typed = cast(list[httpx.Response], responses)
    assert sorted(item.status_code for item in typed) == [200, 409]
    loser = next(item for item in typed if item.status_code == 409)
    assert loser.json()["error"]["code"] == "revision_conflict"
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.queue_entries WHERE organization_id = %s AND id = %s",
        (fixture.organization_id, entry_id),
    ).fetchone() == ("cancelled", revision + 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_waitlist_leave_same_revision_has_one_winner_and_one_revision_conflict(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = waitlist_fixture(admin_conn)
    app = waitlist_app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer operator"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as setup:
        joined = await setup.post(
            "/v1/waitlist",
            json={"offering_id": str(fixture.offering_id), "subject_party_id": str(fixture.subject_party_id)},
            headers={**auth, "Idempotency-Key": f"race-waitlist-{uuid4().hex}"},
        )
    assert joined.status_code == 201
    entry_id = UUID(cast(str, joined.json()["id"]))
    revision = cast(int, joined.json()["revision"])
    path = f"/v1/waitlist/{entry_id}/leave"
    body = {"expected_revision": revision, "reason": "concurrent leave"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as first_client, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as second_client:
        first, second = await race_behind_row_lock(
            admin_conn,
            table="waitlist_entries",
            organization_id=fixture.organization_id,
            aggregate_id=entry_id,
            first=first_client.post(path, json=body, headers={**auth, "Idempotency-Key": f"waitlist-a-{uuid4().hex}"}),
            second=second_client.post(path, json=body, headers={**auth, "Idempotency-Key": f"waitlist-b-{uuid4().hex}"}),
        )

    typed = cast(list[httpx.Response], [first, second])
    assert all(isinstance(item, httpx.Response) for item in typed)
    assert sorted(item.status_code for item in typed) == [200, 409]
    loser = next(item for item in typed if item.status_code == 409)
    assert loser.json()["error"]["code"] == "revision_conflict"
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.waitlist_entries WHERE organization_id = %s AND id = %s",
        (fixture.organization_id, entry_id),
    ).fetchone() == ("cancelled", revision + 1)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_reminder_cancel_same_revision_has_one_winner_and_one_revision_conflict(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = reminder_fixture(admin_conn)
    app = reminder_app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer agent"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as setup:
        created = await setup.post(
            "/v1/reminders",
            json=_create_body(fixture),
            headers={**auth, "Idempotency-Key": f"race-reminder-{uuid4().hex}"},
        )
    assert created.status_code == 201
    plan_id = UUID(cast(str, created.json()["id"]))
    revision = cast(int, created.json()["revision"])
    path = f"/v1/reminders/{plan_id}/cancel"
    body = {"expected_revision": revision, "reason": "concurrent cancel"}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as first_client, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as second_client:
        first, second = await race_behind_row_lock(
            admin_conn,
            table="reminder_plans",
            organization_id=fixture.organization_id,
            aggregate_id=plan_id,
            first=first_client.post(path, json=body, headers={**auth, "Idempotency-Key": f"reminder-a-{uuid4().hex}"}),
            second=second_client.post(path, json=body, headers={**auth, "Idempotency-Key": f"reminder-b-{uuid4().hex}"}),
        )

    typed = cast(list[httpx.Response], [first, second])
    assert all(isinstance(item, httpx.Response) for item in typed)
    assert sorted(item.status_code for item in typed) == [200, 409]
    loser = next(item for item in typed if item.status_code == 409)
    assert loser.json()["error"]["code"] == "revision_conflict"
    assert admin_conn.execute(
        "SELECT status, revision FROM request_engine.reminder_plans WHERE organization_id = %s AND id = %s",
        (fixture.organization_id, plan_id),
    ).fetchone() == ("cancelled", revision + 1)
