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

_REQUEST_CAPABILITIES = frozenset(
    {
        "requests.submit",
        "requests.read",
        "requests.cancel",
        "requests.party_override",
    }
)


@dataclass(frozen=True, slots=True)
class RequestTenantFixture:
    organization_id: UUID
    principal_id: UUID
    requester_party_id: UUID
    recipient_party_id: UUID
    request_key: str


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


def _fixture(conn: PgConnection, label: str) -> RequestTenantFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"request-isolation-{label}-{suffix}", f"Request Isolation {label}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"request-agent-{label}-{suffix}"),
    )

    def party(name: str) -> UUID:
        return _uuid_row(
            conn,
            """
            INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
            VALUES (%s, 'person', %s)
            RETURNING id
            """,
            (organization_id, name),
        )

    requester_party_id = party(f"Requester {label}")
    recipient_party_id = party(f"Recipient {label}")
    request_key = f"callback_{label}_{suffix}"
    definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, %s, true)
        RETURNING id
        """,
        (organization_id, request_key, f"Callback {label}"),
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
    return RequestTenantFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        requester_party_id=requester_party_id,
        recipient_party_id=recipient_party_id,
        request_key=request_key,
    )


def _actor(fixture: RequestTenantFixture) -> ActorContext:
    return ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=_REQUEST_CAPABILITIES,
    )


def _client(
    session_factory: SessionFactory,
    tenant_a: RequestTenantFixture,
    tenant_b: RequestTenantFixture,
) -> AsyncClient:
    app = create_app(
        session_factory=session_factory,
        actor_resolver=BearerResolver(
            {
                "tenant-a": _actor(tenant_a),
                "tenant-b": _actor(tenant_b),
            }
        ),
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _error_shape(response: Response) -> tuple[int, str, str]:
    error = response.json()["error"]
    return response.status_code, cast(str, error["code"]), cast(str, error["resolution"])


def _submit_body(
    requester_party_id: UUID,
    recipient_party_id: UUID,
) -> dict[str, object]:
    return {
        "payload": {"message": "Please call me back"},
        "requester_party_id": str(requester_party_id),
        "recipient_party_id": str(recipient_party_id),
    }


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_foreign_request_and_definition_ids_do_not_create_existence_oracles(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a")
    tenant_b = _fixture(admin_conn, "b")
    headers_a = {"Authorization": "Bearer tenant-a"}
    headers_b = {"Authorization": "Bearer tenant-b"}

    async with _client(app_session_factory, tenant_a, tenant_b) as client:
        submitted_b = await client.post(
            f"/v1/requests/definitions/{tenant_b.request_key}/submit",
            json=_submit_body(tenant_b.requester_party_id, tenant_b.recipient_party_id),
            headers={**headers_b, "Idempotency-Key": f"submit-b-{uuid4().hex}"},
        )
        assert submitted_b.status_code == 201
        request_b = submitted_b.json()["request"]
        request_b_id = UUID(request_b["id"])
        request_b_revision = cast(int, request_b["revision"])

        foreign_read = await client.get(f"/v1/requests/{request_b_id}", headers=headers_a)
        nonexistent_read = await client.get(f"/v1/requests/{uuid4()}", headers=headers_a)
        assert _error_shape(foreign_read) == _error_shape(nonexistent_read)
        assert _error_shape(foreign_read) == (404, "request_not_found", "refresh_and_retry")

        foreign_cancel = await client.post(
            f"/v1/requests/{request_b_id}/cancel",
            json={"reason": "cross-tenant attack", "expected_revision": request_b_revision},
            headers={**headers_a, "Idempotency-Key": f"attack-{uuid4().hex}"},
        )
        nonexistent_cancel = await client.post(
            f"/v1/requests/{uuid4()}/cancel",
            json={"reason": "nonexistent control", "expected_revision": request_b_revision},
            headers={**headers_a, "Idempotency-Key": f"control-{uuid4().hex}"},
        )
        assert _error_shape(foreign_cancel) == _error_shape(nonexistent_cancel)
        assert _error_shape(foreign_cancel) == (404, "request_not_found", "refresh_and_retry")

        foreign_definition = await client.post(
            f"/v1/requests/definitions/{tenant_b.request_key}/submit",
            json=_submit_body(tenant_a.requester_party_id, tenant_a.recipient_party_id),
            headers={**headers_a, "Idempotency-Key": f"foreign-definition-{uuid4().hex}"},
        )
        nonexistent_definition = await client.post(
            f"/v1/requests/definitions/missing-{uuid4().hex}/submit",
            json=_submit_body(tenant_a.requester_party_id, tenant_a.recipient_party_id),
            headers={**headers_a, "Idempotency-Key": f"missing-definition-{uuid4().hex}"},
        )
        assert _error_shape(foreign_definition) == _error_shape(nonexistent_definition)
        assert _error_shape(foreign_definition) == (
            404,
            "request_definition_not_found",
            "fix_request",
        )

        owner_read = await client.get(f"/v1/requests/{request_b_id}", headers=headers_b)
        assert owner_read.status_code == 200
        assert owner_read.json()["status"] == "open"
        assert owner_read.json()["revision"] == request_b_revision

    persisted = admin_conn.execute(
        """
        SELECT organization_id, status, revision
        FROM request_engine.requests
        WHERE id = %s
        """,
        (request_b_id,),
    ).fetchone()
    assert persisted == (tenant_b.organization_id, "open", request_b_revision)


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_request_party_override_cannot_import_parties_from_another_tenant(
    admin_conn: PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    tenant_a = _fixture(admin_conn, "a-party")
    tenant_b = _fixture(admin_conn, "b-party")

    async with _client(app_session_factory, tenant_a, tenant_b) as client:
        foreign_requester = await client.post(
            f"/v1/requests/definitions/{tenant_a.request_key}/submit",
            json=_submit_body(tenant_b.requester_party_id, tenant_a.recipient_party_id),
            headers={
                "Authorization": "Bearer tenant-a",
                "Idempotency-Key": f"foreign-requester-{uuid4().hex}",
            },
        )
        foreign_recipient = await client.post(
            f"/v1/requests/definitions/{tenant_a.request_key}/submit",
            json=_submit_body(tenant_a.requester_party_id, tenant_b.recipient_party_id),
            headers={
                "Authorization": "Bearer tenant-a",
                "Idempotency-Key": f"foreign-recipient-{uuid4().hex}",
            },
        )

        assert _error_shape(foreign_requester) == (
            422,
            "request_party_not_usable",
            "fix_request",
        )
        assert _error_shape(foreign_recipient) == (
            422,
            "request_party_not_usable",
            "fix_request",
        )

    cross_tenant_requests = admin_conn.execute(
        """
        SELECT count(*)
        FROM request_engine.requests
        WHERE organization_id = %s
          AND (
              requester_party_id IN (%s, %s)
              OR recipient_party_id IN (%s, %s)
          )
        """,
        (
            tenant_a.organization_id,
            tenant_b.requester_party_id,
            tenant_b.recipient_party_id,
            tenant_b.requester_party_id,
            tenant_b.recipient_party_id,
        ),
    ).fetchone()
    assert cross_tenant_requests == (0,)
