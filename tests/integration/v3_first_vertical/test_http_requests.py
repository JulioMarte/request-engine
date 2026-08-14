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
from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.application.commands.complete_request import (
    CompleteRequestCommand,
    complete_request,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]

_FULL_REQUEST_CAPABILITIES = frozenset(
    {
        "requests.submit",
        "requests.read",
        "requests.record_result",
        "requests.complete",
        "requests.cancel",
        "requests.fail",
        "requests.party_override",
    }
)


@dataclass(frozen=True, slots=True)
class HttpFixture:
    organization_id: UUID
    principal_id: UUID
    requester_party_id: UUID
    request_key: str
    version_1_id: UUID
    version_2_id: UUID
    other_organization_id: UUID
    other_principal_id: UUID


class BearerTestActorResolver:
    def __init__(self, actors: dict[str, ActorContext]) -> None:
        self._actors = actors

    async def resolve_actor(self, request: Request) -> ActorContext:
        authorization = request.headers.get("authorization")
        if authorization is None or not authorization.startswith("Bearer "):
            raise AuthenticationRequired
        token = authorization.removeprefix("Bearer ")
        actor = self._actors.get(token)
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


def _create_org(conn: PgConnection, prefix: str) -> tuple[UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{suffix}", f"{prefix.title()} {suffix}"),
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
    return organization_id, principal_id


def _create_definition_version(
    conn: PgConnection,
    *,
    organization_id: UUID,
    definition_id: UUID,
    version: int,
) -> UUID:
    input_schema: dict[str, object] = {
        "type": "object",
        "required": ["message"],
        "additionalProperties": False,
        "properties": {"message": {"type": "string", "minLength": 1}},
    }
    result_schema: dict[str, object] = {
        "type": "object",
        "required": ["quote_total"],
        "additionalProperties": False,
        "properties": {"quote_total": {"type": "number", "minimum": 0}},
    }
    return _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id,
            request_definition_id,
            version,
            input_schema,
            result_schema
        ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            definition_id,
            version,
            json.dumps(input_schema),
            json.dumps(result_schema),
        ),
    )


def _create_fixture(conn: PgConnection) -> HttpFixture:
    organization_id, principal_id = _create_org(conn, "http-requests")
    other_organization_id, other_principal_id = _create_org(conn, "http-other")
    suffix = uuid4().hex
    requester_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (
            organization_id, party_kind, display_name
        ) VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Requester {suffix}"),
    )
    request_key = f"request_quote_{suffix}"
    definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, 'Request quote', true)
        RETURNING id
        """,
        (organization_id, request_key),
    )
    version_1_id = _create_definition_version(
        conn,
        organization_id=organization_id,
        definition_id=definition_id,
        version=1,
    )
    version_2_id = _create_definition_version(
        conn,
        organization_id=organization_id,
        definition_id=definition_id,
        version=2,
    )
    return HttpFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        requester_party_id=requester_party_id,
        request_key=request_key,
        version_1_id=version_1_id,
        version_2_id=version_2_id,
        other_organization_id=other_organization_id,
        other_principal_id=other_principal_id,
    )


def _client(
    session_factory: SessionFactory,
    actors: dict[str, ActorContext],
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerTestActorResolver(actors),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_request_surface_requires_authenticated_capability(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "no-submit": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=frozenset({"requests.read"}),
        )
    }
    async with _client(session_factory, actors) as client:
        unauthenticated = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={"Idempotency-Key": f"unauth-{uuid4().hex}"},
            json={"payload": {"message": "hello"}},
        )
        assert unauthenticated.status_code == 401

        forbidden = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer no-submit",
                "Idempotency-Key": f"forbidden-{uuid4().hex}",
            },
            json={"payload": {"message": "hello"}},
        )
        assert forbidden.status_code == 403


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_submit_resolves_latest_version_and_replays_idempotently(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_REQUEST_CAPABILITIES,
        )
    }
    idempotency_key = f"http-submit-{uuid4().hex}"
    body = {
        "payload": {"message": "Please prepare a quote"},
        "requester_party_id": str(fixture.requester_party_id),
        "correlations": [
            {
                "correlation_kind": "conversation",
                "provider_key": "whatsapp",
                "external_key": f"thread-{uuid4().hex}",
            }
        ],
    }
    async with _client(session_factory, actors) as client:
        response = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": idempotency_key,
            },
            json=body,
        )
        replay = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": idempotency_key,
            },
            json=body,
        )

    assert response.status_code == 201
    assert replay.status_code == 201
    response_data = response.json()
    replay_data = replay.json()
    assert response_data == replay_data
    assert response_data["request_key"] == fixture.request_key
    assert response_data["definition_version"] == 2
    assert response_data["request"]["request_definition_version_id"] == str(fixture.version_2_id)

    request_count = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.requests
        WHERE organization_id = %s
          AND id = %s
        """,
        (fixture.organization_id, UUID(response_data["request"]["id"])),
    ).fetchone()
    assert request_count == (1,)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_explicit_definition_version_and_internal_semantic_completion(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_REQUEST_CAPABILITIES,
        )
    }
    async with _client(session_factory, actors) as client:
        created_response = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": f"explicit-{uuid4().hex}",
            },
            json={
                "definition_version": 1,
                "payload": {"message": "Use pinned schema"},
                "requester_party_id": str(fixture.requester_party_id),
            },
        )
        assert created_response.status_code == 201
        created = created_response.json()
        assert created["definition_version"] == 1
        assert created["request"]["request_definition_version_id"] == str(fixture.version_1_id)
        request_id = UUID(created["request"]["id"])

        hidden = await client.post(
            f"/v1/requests/{request_id}/complete",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": f"must-not-route-{uuid4().hex}",
            },
            json={
                "expected_revision": 1,
                "result_payload": {"quote_total": 250.0},
            },
        )
        assert hidden.status_code == 404

    completed = await complete_request(
        PostgresRequestCommands(session_factory),
        CompleteRequestCommand(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            request_id=request_id,
            expected_revision=1,
            result_payload={"quote_total": 250.0},
            idempotency_key=f"complete-{uuid4().hex}",
        ),
    )
    assert completed.status.value == "completed"
    assert completed.revision == 2
    assert completed.result_payload == {"quote_total": 250.0}

    async with _client(session_factory, actors) as client:
        conflict = await client.post(
            f"/v1/requests/{request_id}/cancel",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": f"cancel-{uuid4().hex}",
            },
            json={"expected_revision": 2},
        )
        assert conflict.status_code == 409
        assert conflict.json()["error"]["code"] == "request_not_open"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_tenant_context_cannot_be_spoofed_by_identifier_headers(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    other_request_id = _uuid_row(
        admin_conn,
        """
        WITH definition AS (
            INSERT INTO request_engine.request_definitions (
                organization_id, request_key, display_name
            ) VALUES (%s, %s, 'Other request')
            RETURNING id
        ), version AS (
            INSERT INTO request_engine.request_definition_versions (
                organization_id, request_definition_id, version, input_schema
            )
            SELECT %s, id, 1, '{"type":"object"}'::jsonb
            FROM definition
            RETURNING id
        )
        INSERT INTO request_engine.requests (
            organization_id, request_definition_version_id, payload
        )
        SELECT %s, id, '{}'::jsonb FROM version
        RETURNING id
        """,
        (
            fixture.other_organization_id,
            f"other-{uuid4().hex}",
            fixture.other_organization_id,
            fixture.other_organization_id,
        ),
    )
    actors = {
        "tenant-a": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_REQUEST_CAPABILITIES,
        )
    }
    async with _client(session_factory, actors) as client:
        response = await client.get(
            f"/v1/requests/{other_request_id}",
            headers={
                "Authorization": "Bearer tenant-a",
                "X-Organization-Id": str(fixture.other_organization_id),
                "X-Principal-Id": str(fixture.other_principal_id),
            },
        )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_http_idempotency_key_reuse_with_different_payload_is_conflict(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_REQUEST_CAPABILITIES,
        )
    }
    idempotency_key = f"reuse-{uuid4().hex}"
    async with _client(session_factory, actors) as client:
        first = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": idempotency_key,
            },
            json={"payload": {"message": "first"}},
        )
        second = await client.post(
            f"/v1/requests/definitions/{fixture.request_key}/submit",
            headers={
                "Authorization": "Bearer agent",
                "Idempotency-Key": idempotency_key,
            },
            json={"payload": {"message": "different"}},
        )
    assert first.status_code == 201
    assert second.status_code == 409
    error = second.json()["error"]
    assert error["code"] == "idempotency_conflict"
    assert error["resolution"] == "fix_request"
    assert error["details"]["idempotency_key"] == idempotency_key


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_openapi_does_not_expose_tenant_or_principal_selection_headers(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _create_fixture(admin_conn)
    actors = {
        "agent": ActorContext(
            organization_id=fixture.organization_id,
            principal_id=fixture.principal_id,
            capabilities=_FULL_REQUEST_CAPABILITIES,
        )
    }
    async with _client(session_factory, actors) as client:
        response = await client.get("/openapi.json")
    assert response.status_code == 200
    serialized = json.dumps(response.json())
    assert "X-Organization-Id" not in serialized
    assert "X-Principal-Id" not in serialized
