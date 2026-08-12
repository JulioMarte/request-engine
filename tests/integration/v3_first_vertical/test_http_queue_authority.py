from dataclasses import dataclass
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]

_QUEUE_CAPABILITIES = frozenset({"queue.read", "queue.join", "queue.leave", "queue.call_next"})


@dataclass(frozen=True, slots=True)
class QueueAuthorityFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    queue_id: UUID


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
    query: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection) -> QueueAuthorityFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Queue Authority Practice')
        RETURNING id
        """,
        (f"queue-authority-{suffix}",),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Protected Walk-in Patient')
        RETURNING id
        """,
        (organization_id,),
    )
    queue_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name
        ) VALUES (%s, %s, 'Protected walk-in queue')
        RETURNING id
        """,
        (organization_id, f"walk-in-{suffix}"),
    )
    return QueueAuthorityFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        queue_id=queue_id,
    )


def _grant(conn: PgConnection, fixture: QueueAuthorityFixture, scope_key: str) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_until
        ) VALUES (%s, %s, %s, 'authorized_contact', %s, clock_timestamp() + interval '1 day')
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.principal_id,
            fixture.subject_party_id,
            scope_key,
        ),
    )


def _client(session_factory: SessionFactory, fixture: QueueAuthorityFixture) -> AsyncClient:
    actors = {
        "delegated": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_QUEUE_CAPABILITIES,
        ),
        "operator": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_QUEUE_CAPABILITIES | frozenset({"queue.subject_override"}),
        ),
    }
    app = create_app(session_factory=session_factory, actor_resolver=BearerResolver(actors))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_queue_requires_current_subject_authority_and_records_provenance(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    delegated = {"Authorization": "Bearer delegated"}
    operator = {"Authorization": "Bearer operator"}
    join_body = {"subject_party_id": str(fixture.subject_party_id)}

    async with _client(session_factory, fixture) as client:
        denied = await client.post(
            f"/v1/queues/{fixture.queue_id}/join",
            json=join_body,
            headers={**delegated, "Idempotency-Key": f"denied-{uuid4().hex}"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "subject_authority_required"
        assert denied.json()["error"]["details"]["scope_key"] == "queue.join"

        join_representation_id = _grant(admin_conn, fixture, "queue.join")
        manage_representation_id = _grant(admin_conn, fixture, "queue.manage")
        joined = await client.post(
            f"/v1/queues/{fixture.queue_id}/join",
            json=join_body,
            headers={**delegated, "Idempotency-Key": f"join-{uuid4().hex}"},
        )
        assert joined.status_code == 201

        readable = await client.get(
            f"/v1/queues/{fixture.queue_id}/status",
            params={"subject_party_id": str(fixture.subject_party_id)},
            headers=delegated,
        )
        assert readable.status_code == 200
        assert readable.json()["entry"]["id"] == joined.json()["id"]

        admin_conn.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, manage_representation_id),
        )

        read_after_revoke = await client.get(
            f"/v1/queues/{fixture.queue_id}/status",
            params={"subject_party_id": str(fixture.subject_party_id)},
            headers=delegated,
        )
        leave_after_revoke = await client.post(
            f"/v1/queues/{fixture.queue_id}/leave",
            json={"subject_party_id": str(fixture.subject_party_id), "reason": "denied"},
            headers={**delegated, "Idempotency-Key": f"leave-denied-{uuid4().hex}"},
        )
        assert read_after_revoke.status_code == 403
        assert leave_after_revoke.status_code == 403

        operator_read = await client.get(
            f"/v1/queues/{fixture.queue_id}/status",
            params={"subject_party_id": str(fixture.subject_party_id)},
            headers=operator,
        )
        assert operator_read.status_code == 200

        operator_leave = await client.post(
            f"/v1/queues/{fixture.queue_id}/leave",
            json={"subject_party_id": str(fixture.subject_party_id), "reason": "staff removal"},
            headers={**operator, "Idempotency-Key": f"leave-{uuid4().hex}"},
        )
        assert operator_leave.status_code == 200
        assert operator_leave.json()["status"] == "cancelled"

    audit_rows = admin_conn.execute(
        """
        SELECT command_name, details
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'QueueEntry'
        ORDER BY created_at, id
        """,
        (fixture.organization_id,),
    ).fetchall()
    assert [row[0] for row in audit_rows] == ["queue.join", "queue.leave"]
    assert audit_rows[0][1]["subject_authority"] == {
        "mode": "representation",
        "scope_key": "queue.join",
        "representation_id": str(join_representation_id),
        "authority_kind": "authorized_contact",
    }
    assert audit_rows[1][1]["subject_authority"] == {
        "mode": "operator",
        "scope_key": "queue.manage",
        "representation_id": None,
        "authority_kind": None,
    }
