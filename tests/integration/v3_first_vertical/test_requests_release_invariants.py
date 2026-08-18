import json
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import pytest
from psycopg import Connection, Error

from request_engine.modules.requests.adapters.db.request_commands import PostgresRequestCommands
from request_engine.modules.requests.application.commands.create_request import (
    CreateRequestCommand,
    create_request,
)
from request_engine.modules.requests.application.errors import RequestPayloadInvalid
from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _request_fixture(conn: PgConnection) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"request-release-{suffix}", f"Request release {suffix}"),
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
    party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Requester {suffix}"),
    )
    definition_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name
        ) VALUES (%s, %s, 'Versioned request')
        RETURNING id
        """,
        (organization_id, f"versioned-{suffix}"),
    )
    v1 = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version, input_schema
        ) VALUES (%s, %s, 1, %s::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            definition_id,
            json.dumps(
                {
                    "type": "object",
                    "required": ["message"],
                    "additionalProperties": False,
                    "properties": {"message": {"type": "string"}},
                }
            ),
        ),
    )
    v2 = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version, input_schema
        ) VALUES (%s, %s, 2, %s::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            definition_id,
            json.dumps(
                {
                    "type": "object",
                    "required": ["message"],
                    "additionalProperties": False,
                    "properties": {"message": {"type": "integer"}},
                }
            ),
        ),
    )
    return organization_id, principal_id, party_id, v1, v2


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
async def test_i10_request_payload_is_validated_against_exact_referenced_immutable_version(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    organization_id, principal_id, party_id, v1, v2 = _request_fixture(admin_conn)
    commands = PostgresRequestCommands(session_factory)

    created = await create_request(
        commands,
        CreateRequestCommand(
            organization_id=organization_id,
            principal_id=principal_id,
            request_definition_version_id=v1,
            requester_party_id=party_id,
            payload={"message": "valid only for v1"},
            idempotency_key=f"i10-v1-{uuid4().hex}",
            allow_party_override=True,
        ),
    )
    assert admin_conn.execute(
        """
        SELECT request_definition_version_id, payload
        FROM request_engine.requests
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, created.id),
    ).fetchone() == (v1, {"message": "valid only for v1"})

    with pytest.raises(RequestPayloadInvalid):
        await create_request(
            commands,
            CreateRequestCommand(
                organization_id=organization_id,
                principal_id=principal_id,
                request_definition_version_id=v2,
                requester_party_id=party_id,
                payload={"message": "invalid for v2"},
                idempotency_key=f"i10-v2-{uuid4().hex}",
                allow_party_override=True,
            ),
        )

    with pytest.raises(Error) as immutable_version:
        admin_conn.execute(
            """
            UPDATE request_engine.request_definition_versions
            SET input_schema = '{"type":"object"}'::jsonb
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, v1),
        )
    assert immutable_version.value.sqlstate == "55000"


@pytest.mark.postgres
def test_i11_request_terminal_lifecycle_is_database_monotonic(
    admin_conn: PgConnection,
) -> None:
    organization_id, _principal_id, party_id, v1, _v2 = _request_fixture(admin_conn)
    request_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.requests (
            organization_id, request_definition_version_id, requester_party_id, payload
        ) VALUES (%s, %s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (organization_id, v1, party_id),
    )
    admin_conn.execute(
        """
        UPDATE request_engine.requests
        SET status = 'completed', completed_at = clock_timestamp(), revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, request_id),
    )

    with pytest.raises(Error) as reopened:
        admin_conn.execute(
            """
            UPDATE request_engine.requests
            SET status = 'cancelled', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, request_id),
        )
    assert reopened.value.sqlstate == "23514"
    assert admin_conn.execute(
        """
        SELECT status, revision
        FROM request_engine.requests
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, request_id),
    ).fetchone() == ("completed", 2)
