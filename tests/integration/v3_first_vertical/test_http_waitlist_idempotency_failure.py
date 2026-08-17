# pyright: reportPrivateUsage=false

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
from .test_http_waitlist import BearerResolver, WaitlistFixture, _fixture

PgConnection = Connection[Any]


def _app(session_factory: SessionFactory, fixture: WaitlistFixture) -> FastAPI:
    actor = ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=frozenset(
            {
                "waitlist.join",
                "waitlist.read",
                "waitlist.leave",
                "waitlist.subject_override",
            }
        ),
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver({"operator": actor}),
        appointment_option_signing_key=b"x" * 64,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_waitlist_join_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    path = "/v1/waitlist"
    key = f"lost-waitlist-join-{uuid4().hex}"
    body = {
        "offering_id": str(fixture.offering_id),
        "subject_party_id": str(fixture.subject_party_id),
    }
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {"Authorization": "Bearer operator", "Idempotency-Key": key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(path, json=body, headers=headers)
        replay = await client.post(path, json=body, headers=headers)

    assert replay.status_code == 201
    entry_id = UUID(cast(str, replay.json()["id"]))
    assert replay.json()["status"] == "active"
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.waitlist_entries
        WHERE organization_id = %s
          AND offering_id = %s
          AND subject_party_id = %s
        """,
        (fixture.organization_id, fixture.offering_id, fixture.subject_party_id),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'waitlist.entry_joined.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_waitlist_leave_replays_original_revision_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer operator"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        joined = await client.post(
            "/v1/waitlist",
            json={
                "offering_id": str(fixture.offering_id),
                "subject_party_id": str(fixture.subject_party_id),
            },
            headers={**auth, "Idempotency-Key": f"prepare-waitlist-{uuid4().hex}"},
        )
    assert joined.status_code == 201
    entry_id = UUID(cast(str, joined.json()["id"]))
    revision = cast(int, joined.json()["revision"])

    path = f"/v1/waitlist/{entry_id}/leave"
    key = f"lost-waitlist-leave-{uuid4().hex}"
    body = {"expected_revision": revision, "reason": "response lost"}
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {**auth, "Idempotency-Key": key}
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
        FROM request_engine.waitlist_entries
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == ("cancelled", revision + 1)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'waitlist.entry_cancelled.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, entry_id),
    ).fetchone() == (1,)
