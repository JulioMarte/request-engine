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


@dataclass(frozen=True, slots=True)
class WaitlistFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    offering_id: UUID


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


def _fixture(conn: PgConnection) -> WaitlistFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Waitlist Practice')
        RETURNING id
        """,
        (f"waitlist-{suffix}",),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"waitlist-agent-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Waitlist Patient')
        RETURNING id
        """,
        (organization_id,),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, 'Waitlist Consultation')
        RETURNING id
        """,
        (organization_id, f"consult-{suffix}"),
    )
    return WaitlistFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        offering_id=offering_id,
    )


def _grant(conn: PgConnection, fixture: WaitlistFixture, scope_key: str) -> UUID:
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


def _client(session_factory: SessionFactory, fixture: WaitlistFixture) -> AsyncClient:
    public_capabilities = frozenset({"waitlist.join", "waitlist.read", "waitlist.leave"})
    actors = {
        "delegated": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=public_capabilities,
        ),
        "operator": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=public_capabilities | frozenset({"waitlist.subject_override"}),
        ),
    }
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(actors),
        appointment_option_signing_key=b"x" * 64,
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_waitlist_requires_current_party_authority_and_operator_override(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn)
    delegated = {"Authorization": "Bearer delegated"}
    operator = {"Authorization": "Bearer operator"}
    join_body = {
        "offering_id": str(fixture.offering_id),
        "subject_party_id": str(fixture.subject_party_id),
    }

    async with _client(session_factory, fixture) as client:
        denied = await client.post(
            "/v1/waitlist",
            json=join_body,
            headers={**delegated, "Idempotency-Key": f"denied-{uuid4().hex}"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "party_authority_required"
        assert denied.json()["error"]["details"]["scope_key"] == "waitlist.join"

        join_representation_id = _grant(admin_conn, fixture, "waitlist.join")
        join_key = f"join-{uuid4().hex}"
        joined = await client.post(
            "/v1/waitlist",
            json=join_body,
            headers={**delegated, "Idempotency-Key": join_key},
        )
        replay = await client.post(
            "/v1/waitlist",
            json=join_body,
            headers={**delegated, "Idempotency-Key": join_key},
        )
        assert joined.status_code == 201
        assert replay.status_code == 201
        assert replay.json() == joined.json()
        entry_id = UUID(joined.json()["id"])
        initial_revision = cast(int, joined.json()["revision"])

        read_denied = await client.get(f"/v1/waitlist/{entry_id}", headers=delegated)
        assert read_denied.status_code == 403
        assert read_denied.json()["error"]["details"]["scope_key"] == "waitlist.manage"

        manage_representation_id = _grant(admin_conn, fixture, "waitlist.manage")
        readable = await client.get(f"/v1/waitlist/{entry_id}", headers=delegated)
        assert readable.status_code == 200
        assert readable.json()["status"] == "active"

        admin_conn.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, manage_representation_id),
        )
        after_revoke = await client.get(f"/v1/waitlist/{entry_id}", headers=delegated)
        leave_after_revoke = await client.post(
            f"/v1/waitlist/{entry_id}/leave",
            json={"expected_revision": initial_revision},
            headers={**delegated, "Idempotency-Key": f"leave-denied-{uuid4().hex}"},
        )
        assert after_revoke.status_code == 403
        assert leave_after_revoke.status_code == 403

        operator_read = await client.get(f"/v1/waitlist/{entry_id}", headers=operator)
        assert operator_read.status_code == 200

        admin_conn.execute(
            """
            UPDATE request_engine.waitlist_entries
            SET updated_at = clock_timestamp()
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, entry_id),
        )
        stale_leave = await client.post(
            f"/v1/waitlist/{entry_id}/leave",
            json={"expected_revision": initial_revision},
            headers={**operator, "Idempotency-Key": f"stale-{uuid4().hex}"},
        )
        assert stale_leave.status_code == 409
        assert stale_leave.json()["error"]["code"] == "revision_conflict"
        current_revision = cast(int, stale_leave.json()["error"]["details"]["current_revision"])

        leave_key = f"leave-{uuid4().hex}"
        left = await client.post(
            f"/v1/waitlist/{entry_id}/leave",
            json={"expected_revision": current_revision, "reason": "patient declined waitlist"},
            headers={**operator, "Idempotency-Key": leave_key},
        )
        leave_replay = await client.post(
            f"/v1/waitlist/{entry_id}/leave",
            json={"expected_revision": current_revision, "reason": "patient declined waitlist"},
            headers={**operator, "Idempotency-Key": leave_key},
        )
        assert left.status_code == 200
        assert left.json()["status"] == "cancelled"
        assert leave_replay.json() == left.json()

    audit_rows = admin_conn.execute(
        """
        SELECT command_name, details
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'WaitlistEntry'
          AND aggregate_id = %s
        ORDER BY created_at, id
        """,
        (fixture.organization_id, entry_id),
    ).fetchall()
    assert [row[0] for row in audit_rows] == ["waitlist.join", "waitlist.leave"]
    assert audit_rows[0][1]["subject_authority"] == {
        "mode": "representation",
        "scope_key": "waitlist.join",
        "representation_id": str(join_representation_id),
        "authority_kind": "authorized_contact",
    }
    assert audit_rows[1][1]["subject_authority"] == {
        "mode": "operator",
        "scope_key": "waitlist.manage",
        "representation_id": None,
        "authority_kind": None,
    }
