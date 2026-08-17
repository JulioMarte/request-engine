from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI, Request
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

from ._response_loss import DropFirstMatchingResponseTransport
from .test_communications_reminders import CommunicationFixture, _create_fixture

PgConnection = Connection[Any]


class ReminderBearerResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        if request.headers.get("authorization") != "Bearer agent":
            raise AuthenticationRequired
        return self._actor


def _app(session_factory: SessionFactory, fixture: CommunicationFixture) -> FastAPI:
    actor = ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=frozenset(
            {"reminders.create_plan", "reminders.read", "reminders.cancel_plan"}
        ),
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=ReminderBearerResolver(actor),
    )


def _create_body(fixture: CommunicationFixture) -> dict[str, object]:
    return {
        "subject_party_id": str(fixture.party_id),
        "purpose": "medication_reminder",
        "timezone": "America/Santo_Domingo",
        "daily_times": ["08:00:00", "20:00:00"],
        "max_lateness_minutes": 45,
        "channel_policy": {"channels": ["whatsapp"], "provider_key": "n8n"},
        "template_key": "medication-reminder",
        "template_version": 1,
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_create_replays_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    key = f"lost-reminder-create-{uuid4().hex}"
    path = "/v1/reminders"
    transport = DropFirstMatchingResponseTransport(
        app,
        matches=lambda request: request.method == "POST" and request.url.path == path,
    )
    headers = {"Authorization": "Bearer agent", "Idempotency-Key": key}
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with pytest.raises(httpx.ReadError, match="simulated response loss"):
            await client.post(path, json=_create_body(fixture), headers=headers)
        replay = await client.post(path, json=_create_body(fixture), headers=headers)

    assert replay.status_code == 201
    plan_id = UUID(cast(str, replay.json()["id"]))
    assert replay.json()["status"] == "active"
    assert replay.json()["revision"] == 1
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reminder_plans
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
          AND status = 'pending'
        """,
        (fixture.organization_id, plan_id),
    ).fetchone() == (1,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reminder_plan.created.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone() == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_cancel_replays_original_revision_after_committed_response_loss(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    app = _app(app_session_factory, fixture)
    auth = {"Authorization": "Bearer agent"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        created = await client.post(
            "/v1/reminders",
            json=_create_body(fixture),
            headers={**auth, "Idempotency-Key": f"prepare-reminder-{uuid4().hex}"},
        )
    assert created.status_code == 201
    plan_id = UUID(cast(str, created.json()["id"]))
    revision = cast(int, created.json()["revision"])

    path = f"/v1/reminders/{plan_id}/cancel"
    key = f"lost-reminder-cancel-{uuid4().hex}"
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
        FROM request_engine.reminder_plans
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone() == ("cancelled", revision + 1)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE organization_id = %s
          AND subject_kind = 'ReminderPlan'
          AND subject_id = %s
          AND status = 'pending'
        """,
        (fixture.organization_id, plan_id),
    ).fetchone() == (0,)
    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s
          AND event_type = 'reminder_plan.cancelled.v1'
          AND aggregate_id = %s
        """,
        (fixture.organization_id, plan_id),
    ).fetchone() == (1,)
