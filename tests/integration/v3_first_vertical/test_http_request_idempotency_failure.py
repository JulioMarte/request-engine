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
from .test_http_requests import (
    _FULL_REQUEST_CAPABILITIES,
    BearerTestActorResolver,
    HttpFixture,
    _create_fixture,
)

PgConnection = Connection[Any]


def _app(session_factory: SessionFactory, fixture: HttpFixture) -> FastAPI:
    actor = ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_FULL_REQUEST_CAPABILITIES,
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver({"agent": actor}),
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_request_submit_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    key = f"lost-submit-{uuid4().hex}"
    body = {
        "payload": {"message": "response may disappear"},
        "requester_party_id": str(fixture.requester_party_id),
    }
    path = f"/v1/requests/definitions/{fixture.request_key}/submit"
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
    request_id = UUID(cast(str, replay.json()["request"]["id"]))
    stored = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.requests
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, request_id),
    ).fetchone()
    assert stored == ("open", 1)

    idem = admin_conn.execute(
        """
        SELECT status, result_data -> 'request' ->> 'id'
        FROM request_engine.idempotency_records
        WHERE organization_id = %s
          AND principal_id = %s
          AND capability = 'requests.submit'
          AND idempotency_key = %s
        """,
        (fixture.organization_id, fixture.principal_id, key),
    ).fetchone()
    assert idem == ("completed", str(request_id))

    consequences = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND aggregate_kind = 'Request'
          AND aggregate_id = %s
          AND event_type = 'request.created.v1'
        """,
        (fixture.organization_id, request_id),
    ).fetchone()
    assert consequences == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_request_cancel_replays_original_revision_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer agent"}
    submit_key = f"prepare-submit-{uuid4().hex}"
    submit_path = f"/v1/requests/definitions/{fixture.request_key}/submit"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            submit_path,
            json={
                "payload": {"message": "cancel me"},
                "requester_party_id": str(fixture.requester_party_id),
            },
            headers={**auth, "Idempotency-Key": submit_key},
        )
    assert created.status_code == 201
    request_data = created.json()["request"]
    request_id = UUID(cast(str, request_data["id"]))
    original_revision = cast(int, request_data["revision"])

    cancel_path = f"/v1/requests/{request_id}/cancel"
    cancel_key = f"lost-cancel-{uuid4().hex}"
    body = {"expected_revision": original_revision, "reason": "no longer needed"}
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == cancel_path,
    )
    headers = {**auth, "Idempotency-Key": cancel_key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(cancel_path, json=body, headers=headers)
        replay = await client.post(cancel_path, json=body, headers=headers)

    assert replay.status_code == 200
    assert replay.json()["status"] == "cancelled"
    assert replay.json()["revision"] == original_revision + 1

    stored = admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.requests
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, request_id),
    ).fetchone()
    assert stored == ("cancelled", original_revision + 1)

    consequences = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND aggregate_kind = 'Request'
          AND aggregate_id = %s
          AND event_type = 'request.cancelled.v1'
        """,
        (fixture.organization_id, request_id),
    ).fetchone()
    assert consequences == (1,)
