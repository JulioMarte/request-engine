import json
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
class AuthorityFixture:
    organization_id: UUID
    principal_id: UUID
    requester_party_id: UUID
    recipient_party_id: UUID
    request_key: str


class BearerTestActorResolver:
    def __init__(self, actors: dict[str, ActorContext]) -> None:
        self._actors = actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization")
        if authorization is None or not authorization.startswith("Bearer "):
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


def _create_fixture(conn: PgConnection) -> AuthorityFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Request authority practice')
        RETURNING id
        """,
        (f"request-authority-{suffix}",),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"request-agent-{suffix}"),
    )

    def create_party(name: str) -> UUID:
        return _uuid_row(
            conn,
            """
            INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
            VALUES (%s, 'person', %s)
            RETURNING id
            """,
            (organization_id, name),
        )

    requester_party_id = create_party("Actual requester")
    recipient_party_id = create_party("Recipient only")
    request_key = f"request_callback_{suffix}"
    definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, 'Request callback', true)
        RETURNING id
        """,
        (organization_id, request_key),
    )
    conn.execute(
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version, input_schema
        ) VALUES (
            %s, %s, 1,
            '{"type":"object","required":["message"],"additionalProperties":false,"properties":{"message":{"type":"string","minLength":1}}}'::jsonb
        )
        """,
        (organization_id, definition_id),
    )
    return AuthorityFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        requester_party_id=requester_party_id,
        recipient_party_id=recipient_party_id,
        request_key=request_key,
    )


def _grant(
    conn: PgConnection,
    fixture: AuthorityFixture,
    *,
    party_id: UUID,
    scope_key: str,
    authority_kind: str = "delegated",
) -> UUID:
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            authority_kind,
            scope_key
        ) VALUES (%s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            fixture.organization_id,
            fixture.principal_id,
            party_id,
            authority_kind,
            scope_key,
        ),
    )


def _client(session_factory: SessionFactory, actors: dict[str, ActorContext]) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver(actors),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_requester_is_the_only_party_authority_anchor_and_override_is_audited(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "delegated": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset({"requests.submit", "requests.read", "requests.cancel"}),
        ),
        "operator": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset(
                {"requests.submit", "requests.read", "requests.cancel", "requests.party_override"}
            ),
        ),
    }
    delegated = {"Authorization": "Bearer delegated"}
    operator = {"Authorization": "Bearer operator"}
    body = {
        "payload": {"message": "Please call me back"},
        "requester_party_id": str(fixture.requester_party_id),
        "recipient_party_id": str(fixture.recipient_party_id),
        "participants": [
            {
                "party_id": str(fixture.recipient_party_id),
                "role_key": "authorized_contact",
            }
        ],
    }

    async with _client(session_factory, actors) as client:
        denied_submit = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={**delegated, "Idempotency-Key": f"denied-{uuid4().hex}"},
            json=body,
        )
        assert denied_submit.status_code == 403
        assert denied_submit.json()["error"]["code"] == "request_party_authority_required"
        assert denied_submit.json()["error"]["details"]["scope_key"] == "requests.submit"

        submit_representation_id = _grant(
            admin_conn,
            fixture,
            party_id=fixture.requester_party_id,
            scope_key="requests.submit",
            authority_kind="authorized_contact",
        )
        submitted = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={**delegated, "Idempotency-Key": f"submit-{uuid4().hex}"},
            json=body,
        )
        assert submitted.status_code == 201
        request_id = UUID(submitted.json()["request"]["id"])

        _grant(
            admin_conn,
            fixture,
            party_id=fixture.recipient_party_id,
            scope_key="requests.manage",
        )
        recipient_is_not_authority = await client.get(
            f"/v1/requests/{request_id}",
            headers=delegated,
        )
        assert recipient_is_not_authority.status_code == 403

        manage_representation_id = _grant(
            admin_conn,
            fixture,
            party_id=fixture.requester_party_id,
            scope_key="requests.manage",
            authority_kind="guardian",
        )
        readable = await client.get(f"/v1/requests/{request_id}", headers=delegated)
        assert readable.status_code == 200
        assert readable.json()["requester_party_id"] == str(fixture.requester_party_id)

        admin_conn.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked'
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, manage_representation_id),
        )
        revoked_read = await client.get(f"/v1/requests/{request_id}", headers=delegated)
        revoked_cancel = await client.post(
            f"/v1/requests/{request_id}/cancel",
            headers={**delegated, "Idempotency-Key": f"revoked-cancel-{uuid4().hex}"},
            json={"reason": "should be denied"},
        )
        assert revoked_read.status_code == 403
        assert revoked_cancel.status_code == 403

        operator_read = await client.get(f"/v1/requests/{request_id}", headers=operator)
        assert operator_read.status_code == 200
        cancelled = await client.post(
            f"/v1/requests/{request_id}/cancel",
            headers={**operator, "Idempotency-Key": f"operator-cancel-{uuid4().hex}"},
            json={"reason": "operator decision"},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

    audit_rows = admin_conn.execute(
        """
        SELECT command_name, details
        FROM request_engine.audit_records
        WHERE organization_id = %s
          AND aggregate_kind = 'Request'
          AND aggregate_id = %s
          AND command_name IN ('requests.submit', 'requests.cancel')
        ORDER BY occurred_at, id
        """,
        (fixture.organization_id, request_id),
    ).fetchall()
    assert len(audit_rows) == 2
    submit_details = cast(dict[str, object], audit_rows[0][1])
    cancel_details = cast(dict[str, object], audit_rows[1][1])
    submit_authority = cast(dict[str, object], submit_details["party_authority"])
    cancel_authority = cast(dict[str, object], cancel_details["party_authority"])
    assert submit_authority == {
        "mode": "representation",
        "scope_key": "requests.submit",
        "representation_id": str(submit_representation_id),
        "authority_kind": "authorized_contact",
    }
    assert cancel_authority == {
        "mode": "operator",
        "scope_key": "requests.manage",
        "representation_id": None,
        "authority_kind": None,
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_unattributed_request_can_be_submitted_but_is_operator_managed(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "submitter": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset({"requests.submit", "requests.read"}),
        ),
        "operator": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset({"requests.read", "requests.party_override"}),
        ),
    }
    async with _client(session_factory, actors) as client:
        submitted = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer submitter",
                "Idempotency-Key": f"anonymous-{uuid4().hex}",
            },
            json={"payload": {"message": "Anonymous demand"}},
        )
        assert submitted.status_code == 201
        request_id = submitted.json()["request"]["id"]

        denied = await client.get(
            f"/v1/requests/{request_id}",
            headers={"Authorization": "Bearer submitter"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["details"]["requester_party_id"] is None

        operator_read = await client.get(
            f"/v1/requests/{request_id}",
            headers={"Authorization": "Bearer operator"},
        )
        assert operator_read.status_code == 200
