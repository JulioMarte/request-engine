import asyncio
import os
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import Request
from httpx import ASGITransport, AsyncClient
from psycopg import Connection
from psycopg.errors import LockNotAvailable

from request_engine.entrypoints.http.app import create_app
from request_engine.entrypoints.http.security import AuthenticationRequired
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.security.context import ActorContext

PgConnection = Connection[Any]


class SingleActorResolver:
    def __init__(self, actor: ActorContext) -> None:
        self._actor = actor

    async def resolve_actor(self, request: Request) -> ActorContext:
        if request.headers.get("authorization") != "Bearer represented":
            raise AuthenticationRequired
        return self._actor


def _connect(*, autocommit: bool = False) -> PgConnection:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_v3")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "request_engine")
    return psycopg.connect(
        f"host={host} port={port} dbname={database} user={user} password={password}",
        autocommit=autocommit,
    )


def _uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


async def _wait_until_request_is_blocked_after_authority_lock(
    observer: PgConnection,
) -> None:
    for _ in range(200):
        row = observer.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND wait_event_type = 'Lock'
              AND query LIKE '%%pg_advisory_xact_lock%%'
            """
        ).fetchone()
        assert row is not None
        if cast(int, row[0]) >= 1:
            return
        await asyncio.sleep(0.01)
    pytest.fail("Request submit never reached the post-authority advisory lock barrier")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_request_submit_holds_representation_authority_until_material_command_commit(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Request authority race')
        RETURNING id
        """,
        (f"request-authority-race-{suffix}",),
    )
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"represented-{suffix}"),
    )
    requester_party_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Requester')
        RETURNING id
        """,
        (organization_id,),
    )
    representation_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.representations (
            organization_id,
            principal_id,
            represented_party_id,
            authority_kind,
            scope_key,
            valid_from,
            valid_until
        ) VALUES (
            %s, %s, %s, 'delegated', 'requests.submit',
            clock_timestamp() - interval '1 minute',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, requester_party_id),
    )
    definition_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.request_definitions (
            organization_id, request_key, display_name, active
        ) VALUES (%s, %s, 'Authority race request', true)
        RETURNING id
        """,
        (organization_id, f"authority_race_{suffix}"),
    )
    admin_conn.execute(
        """
        INSERT INTO request_engine.request_definition_versions (
            organization_id, request_definition_id, version, input_schema
        ) VALUES (
            %s, %s, 1,
            '{"type":"object","required":["message"],"properties":{"message":{"type":"string"}}}'::jsonb
        )
        """,
        (organization_id, definition_id),
    )

    correlation_kind = "race"
    provider_key = "test-provider"
    external_key = f"blocked-{suffix}"
    correlation_identity = (
        f"request-correlation:{organization_id}:{correlation_kind}:{provider_key}:{external_key}"
    )

    blocker = _connect()
    revoker = _connect()
    try:
        blocker.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (correlation_identity,),
        )

        actor = ActorContext(
            organization_id=organization_id,
            principal_id=principal_id,
            capabilities=frozenset({"requests.submit"}),
        )
        app = create_app(
            session_factory=session_factory,
            actor_resolver=SingleActorResolver(actor),
        )
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            submit_task = asyncio.create_task(
                client.post(
                    f"/v1/requests/definitions/authority_race_{suffix}/submit",
                    json={
                        "payload": {"message": "authorized before concurrent revoke"},
                        "requester_party_id": str(requester_party_id),
                        "correlations": [
                            {
                                "correlation_kind": correlation_kind,
                                "provider_key": provider_key,
                                "external_key": external_key,
                            }
                        ],
                    },
                    headers={
                        "Authorization": "Bearer represented",
                        "Idempotency-Key": f"request-authority-race-{suffix}",
                    },
                )
            )

            await _wait_until_request_is_blocked_after_authority_lock(admin_conn)

            revoker.execute("SET LOCAL lock_timeout = '250ms'")
            with pytest.raises(LockNotAvailable):
                revoker.execute(
                    """
                    UPDATE request_engine.representations
                    SET status = 'revoked', revision = revision + 1
                    WHERE organization_id = %s AND id = %s
                    """,
                    (organization_id, representation_id),
                )
            revoker.rollback()

            blocker.commit()
            submitted = await asyncio.wait_for(submit_task, timeout=5)
            assert submitted.status_code == 201
            request_id = UUID(submitted.json()["request"]["id"])

            updated = revoker.execute(
                """
                UPDATE request_engine.representations
                SET status = 'revoked', revision = revision + 1
                WHERE organization_id = %s AND id = %s
                """,
                (organization_id, representation_id),
            )
            assert updated.rowcount == 1
            revoker.commit()

            rejected_after_revoke = await client.post(
                f"/v1/requests/definitions/authority_race_{suffix}/submit",
                json={
                    "payload": {"message": "must fail after revoke"},
                    "requester_party_id": str(requester_party_id),
                },
                headers={
                    "Authorization": "Bearer represented",
                    "Idempotency-Key": f"request-after-revoke-{suffix}",
                },
            )
            assert rejected_after_revoke.status_code == 403
            assert rejected_after_revoke.json()["error"]["code"] == "party_authority_required"

        persisted = admin_conn.execute(
            """
            SELECT organization_id, requester_party_id, status, revision
            FROM request_engine.requests
            WHERE id = %s
            """,
            (request_id,),
        ).fetchone()
        assert persisted == (organization_id, requester_party_id, "open", 1)
    finally:
        if not blocker.closed:
            blocker.rollback()
        if not revoker.closed:
            revoker.rollback()
        blocker.close()
        revoker.close()
