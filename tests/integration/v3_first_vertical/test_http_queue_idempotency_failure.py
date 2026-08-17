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


def _app(session_factory: SessionFactory, fixture: OperationsFixture) -> FastAPI:
    actor = ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_FULL_CAPABILITIES,
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver({"agent": actor}),
    )


async def _join(
    client: httpx.AsyncClient,
    fixture: OperationsFixture,
    *,
    key: str,
) -> dict[str, object]:
    response = await client.post(
        f"/v1/queues/{fixture.queue_id}/join",
        json={
            "subject_party_id": str(fixture.subject_party_id),
            "offering_id": str(fixture.offering_id),
        },
        headers={"Authorization": "Bearer agent", "Idempotency-Key": key},
    )
    assert response.status_code == 201
    return cast(dict[str, object], response.json())


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_queue_join_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    path = f"/v1/queues/{fixture.queue_id}/join"
    key = f"lost-queue-join-{uuid4().hex}"
    body = {
        "subject_party_id": str(fixture.subject_party_id),
        "offering_id": str(fixture.offering_id),
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

    assert replay.status_code == 201
    entry_id = UUID(cast(str, replay.json()["id"]))
    assert replay.json()["status"] == "waiting"
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.queue_entries
        WHERE organization_id = %s
          AND service_queue_id = %s
          AND subject_party_id = %s
        """,
        (fixture.organization_id, fixture.queue_id, fixture.subject_party_id),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND command_name = 'queue.join'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_queue_leave_replays_original_revision_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        entry = await _join(client, fixture, key=f"prepare-join-{uuid4().hex}")

    entry_id = UUID(cast(str, entry["id"]))
    revision = cast(int, entry["revision"])
    path = f"/v1/queues/{fixture.queue_id}/entries/{entry_id}/leave"
    key = f"lost-queue-leave-{uuid4().hex}"
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
    assert admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.queue_entries
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == ("cancelled", revision + 1)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'queue.entry_cancelled.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_queue_call_next_replays_server_selected_entry_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        entry = await _join(client, fixture, key=f"prepare-call-next-{uuid4().hex}")

    entry_id = UUID(cast(str, entry["id"]))
    path = f"/v1/queues/{fixture.queue_id}/call-next"
    key = f"lost-call-next-{uuid4().hex}"
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {"Authorization": "Bearer agent", "Idempotency-Key": key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(path, headers=headers)
        replay = await client.post(path, headers=headers)

    assert replay.status_code == 200
    assert UUID(cast(str, replay.json()["id"])) == entry_id
    assert replay.json()["status"] == "called"
    assert replay.json()["revision"] == cast(int, entry["revision"]) + 1
    assert admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.queue_entries
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == ("called", cast(int, entry["revision"]) + 1)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'queue.entry_called.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == (1,)
