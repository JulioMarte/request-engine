from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient, Response
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]

_REMINDER_CAPABILITIES = frozenset(
    {
        "reminders.create_plan",
        "reminders.read",
        "reminders.cancel_plan",
        "reminders.subject_override",
    }
)


@dataclass(frozen=True, slots=True)
class ReminderTenantFixture:
    organization_id: UUID
    principal_id: UUID
    party_id: UUID


class BearerResolver:
    def __init__(self, actors: dict[str, ActorContext]) -> None:
        self._actors = actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise AuthenticationRequired
        actor = self._actors.get(authorization.removeprefix("Bearer "))
        if actor is None:
            raise AuthenticationRequired
        return actor


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, label: str) -> ReminderTenantFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"reminder-isolation-{label}-{suffix}", f"Reminder Isolation {label}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"reminder-agent-{label}-{suffix}"),
    )
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Reminder Patient {label}"),
    )
    return ReminderTenantFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        party_id=party_id,
    )


def _actor(fixture: ReminderTenantFixture) -> ActorContext:
    return ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_REMINDER_CAPABILITIES,
    )


def _client(
    session_factory: SessionFactory,
    tenant_a: ReminderTenantFixture,
    tenant_b: ReminderTenantFixture,
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(
            {
                "tenant-a": _actor(tenant_a),
                "tenant-b": _actor(tenant_b),
            }
        ),
        appointment_option_signing_key=b"x" * 64,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _create_body(subject_party_id: UUID) -> dict[str, object]:
    return {
        "subject_party_id": str(subject_party_id),
        "purpose": "medication_reminder",
        "timezone": "America/Santo_Domingo",
        "daily_times": ["08:00:00"],
        "max_lateness_minutes": 60,
        "channel_policy": {"channels": ["whatsapp"]},
        "template_key": "medication-reminder",
        "template_version": 1,
    }


def _error_shape(response: Response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, cast(str, error["code"]), cast(str, error["resolution"])


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_reminder_plan_ids_behave_like_nonexistent_ids(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a")
    tenant_b = _fixture(admin_conn, "b")
    headers_a = {"Authorization": "Bearer tenant-a"}
    headers_b = {"Authorization": "Bearer tenant-b"}

    async with _client(app_session_factory, tenant_a, tenant_b) as client:
        created_b = await client.post(
            "/v1/reminders",
            json=_create_body(tenant_b.party_id),
            headers={**headers_b, "Idempotency-Key": f"create-b-{uuid4().hex}"},
        )
        assert created_b.status_code == 201
        plan_id = UUID(created_b.json()["id"])
        revision = cast(int, created_b.json()["revision"])

        foreign_read = await client.get(f"/v1/reminders/{plan_id}", headers=headers_a)
        nonexistent_read = await client.get(f"/v1/reminders/{uuid4()}", headers=headers_a)
        assert _error_shape(foreign_read) == _error_shape(nonexistent_read)
        assert _error_shape(foreign_read) == (
            404,
            "reminder_plan_not_found",
            "refresh_and_retry",
        )

        foreign_cancel = await client.post(
            f"/v1/reminders/{plan_id}/cancel",
            json={"expected_revision": revision, "reason": "cross-tenant attack"},
            headers={**headers_a, "Idempotency-Key": f"foreign-cancel-{uuid4().hex}"},
        )
        nonexistent_cancel = await client.post(
            f"/v1/reminders/{uuid4()}/cancel",
            json={"expected_revision": revision, "reason": "nonexistent control"},
            headers={**headers_a, "Idempotency-Key": f"missing-cancel-{uuid4().hex}"},
        )
        assert _error_shape(foreign_cancel) == _error_shape(nonexistent_cancel)
        assert _error_shape(foreign_cancel) == (
            404,
            "reminder_plan_not_found",
            "refresh_and_retry",
        )

        owner_read = await client.get(f"/v1/reminders/{plan_id}", headers=headers_b)
        assert owner_read.status_code == 200
        assert owner_read.json()["status"] == "active"
        assert owner_read.json()["revision"] == revision

    assert admin_conn.execute(
        """
        SELECT organization_id, status, revision
        FROM request_engine.reminder_plans
        WHERE id = %s
        """,
        (plan_id,),
    ).fetchone() == (tenant_b.organization_id, "active", revision)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_reminder_subject_override_cannot_import_foreign_party(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a-override")
    tenant_b = _fixture(admin_conn, "b-override")
    headers_a = {"Authorization": "Bearer tenant-a"}

    async with _client(app_session_factory, tenant_a, tenant_b) as client:
        foreign_subject = await client.post(
            "/v1/reminders",
            json=_create_body(tenant_b.party_id),
            headers={**headers_a, "Idempotency-Key": f"foreign-subject-{uuid4().hex}"},
        )
        nonexistent_subject = await client.post(
            "/v1/reminders",
            json=_create_body(uuid4()),
            headers={**headers_a, "Idempotency-Key": f"missing-subject-{uuid4().hex}"},
        )

        assert foreign_subject.json() == nonexistent_subject.json()
        assert _error_shape(foreign_subject) == (
            422,
            "tenant_reference_not_usable",
            "fix_request",
        )
        assert foreign_subject.json()["error"]["details"] == {
            "reference_kind": "subject_party_id"
        }

    assert admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.reminder_plans
        WHERE organization_id = %s
        """,
        (tenant_a.organization_id,),
    ).fetchone() == (0,)
