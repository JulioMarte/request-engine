import asyncio
import os
from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class AuthorityRaceFixture:
    organization_id: UUID
    principal_id: UUID
    subject_party_id: UUID
    representation_id: UUID
    offering_id: UUID
    queue_id: UUID


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
    statement: LiteralString,
    params: tuple[object, ...],
) -> UUID:
    row = conn.execute(statement, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def _fixture(conn: PgConnection, *, scope_key: str, label: str) -> AuthorityRaceFixture:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"authority-race-{label}-{suffix}", f"Authority race {label}"),
    )
    principal_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s)
        RETURNING id
        """,
        (organization_id, f"represented-{label}-{suffix}"),
    )
    subject_party_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, f"Subject {label}"),
    )
    representation_id = _uuid_row(
        conn,
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
            %s, %s, %s, 'delegated', %s,
            clock_timestamp() - interval '1 minute',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, subject_party_id, scope_key),
    )
    offering_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.offerings (
            organization_id, offering_key, display_name
        ) VALUES (%s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"offering-{label}-{suffix}", f"Offering {label}"),
    )
    queue_id = _uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name, offering_id
        ) VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (organization_id, f"queue-{label}-{suffix}", f"Queue {label}", offering_id),
    )
    return AuthorityRaceFixture(
        organization_id=organization_id,
        principal_id=principal_id,
        subject_party_id=subject_party_id,
        representation_id=representation_id,
        offering_id=offering_id,
        queue_id=queue_id,
    )


async def _wait_until_material_command_is_blocked(
    observer: PgConnection,
    relation_name: str,
) -> None:
    for _ in range(300):
        row = observer.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND wait_event_type = 'Lock'
              AND query ILIKE %s
            """,
            (f"%request_engine.{relation_name}%",),
        ).fetchone()
        assert row is not None
        if cast(int, row[0]) >= 1:
            return
        await asyncio.sleep(0.01)
    pytest.fail(f"material command never reached the {relation_name} lock barrier")


def _assert_revoke_is_blocked(
    revoker: PgConnection,
    fixture: AuthorityRaceFixture,
) -> None:
    revoker.execute("SET LOCAL lock_timeout = '250ms'")
    with pytest.raises(LockNotAvailable):
        revoker.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (fixture.organization_id, fixture.representation_id),
        )
    revoker.rollback()


def _revoke(revoker: PgConnection, fixture: AuthorityRaceFixture) -> None:
    updated = revoker.execute(
        """
        UPDATE request_engine.representations
        SET status = 'revoked', revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (fixture.organization_id, fixture.representation_id),
    )
    assert updated.rowcount == 1
    revoker.commit()


def _app(session_factory: SessionFactory, fixture: AuthorityRaceFixture, capability: str):
    actor = ActorContext(
        organization_id=fixture.organization_id,
        principal_id=fixture.principal_id,
        capabilities=frozenset({capability}),
    )
    return create_app(
        session_factory=session_factory,
        actor_resolver=SingleActorResolver(actor),
        appointment_option_signing_key=b"x" * 64,
    )


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_queue_join_holds_representation_authority_until_commit(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn, scope_key="queue.join", label="queue")
    blocker = _connect()
    revoker = _connect()
    try:
        blocker.execute(
            """
            SELECT id
            FROM request_engine.service_queues
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, fixture.queue_id),
        ).fetchone()

        async with AsyncClient(
            transport=ASGITransport(app=_app(session_factory, fixture, "queue.join")),
            base_url="http://test",
        ) as client:
            join_task = asyncio.create_task(
                client.post(
                    f"/v1/queues/{fixture.queue_id}/join",
                    json={"subject_party_id": str(fixture.subject_party_id)},
                    headers={
                        "Authorization": "Bearer represented",
                        "Idempotency-Key": f"queue-authority-race-{uuid4().hex}",
                    },
                )
            )
            await _wait_until_material_command_is_blocked(admin_conn, "service_queues")
            _assert_revoke_is_blocked(revoker, fixture)

            blocker.commit()
            joined = await asyncio.wait_for(join_task, timeout=5)
            assert joined.status_code == 201
            entry_id = UUID(joined.json()["id"])

            _revoke(revoker, fixture)
            rejected = await client.post(
                f"/v1/queues/{fixture.queue_id}/join",
                json={"subject_party_id": str(fixture.subject_party_id)},
                headers={
                    "Authorization": "Bearer represented",
                    "Idempotency-Key": f"queue-after-revoke-{uuid4().hex}",
                },
            )
            assert rejected.status_code == 403
            assert rejected.json()["error"]["code"] == "party_authority_required"

        persisted = admin_conn.execute(
            """
            SELECT organization_id, service_queue_id, subject_party_id, status, revision
            FROM request_engine.queue_entries
            WHERE id = %s
            """,
            (entry_id,),
        ).fetchone()
        assert persisted == (
            fixture.organization_id,
            fixture.queue_id,
            fixture.subject_party_id,
            "waiting",
            1,
        )
    finally:
        if not blocker.closed:
            blocker.rollback()
        if not revoker.closed:
            revoker.rollback()
        blocker.close()
        revoker.close()


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.postgres
@pytest.mark.concurrency
async def test_waitlist_join_holds_representation_authority_until_commit(
    admin_conn: PgConnection,
    session_factory: SessionFactory,
) -> None:
    fixture = _fixture(admin_conn, scope_key="waitlist.join", label="waitlist")
    blocker = _connect()
    revoker = _connect()
    try:
        blocker.execute(
            """
            SELECT id
            FROM request_engine.offerings
            WHERE organization_id = %s AND id = %s
            FOR UPDATE
            """,
            (fixture.organization_id, fixture.offering_id),
        ).fetchone()

        async with AsyncClient(
            transport=ASGITransport(app=_app(session_factory, fixture, "waitlist.join")),
            base_url="http://test",
        ) as client:
            join_task = asyncio.create_task(
                client.post(
                    "/v1/waitlist",
                    json={
                        "offering_id": str(fixture.offering_id),
                        "subject_party_id": str(fixture.subject_party_id),
                    },
                    headers={
                        "Authorization": "Bearer represented",
                        "Idempotency-Key": f"waitlist-authority-race-{uuid4().hex}",
                    },
                )
            )
            await _wait_until_material_command_is_blocked(admin_conn, "offerings")
            _assert_revoke_is_blocked(revoker, fixture)

            blocker.commit()
            joined = await asyncio.wait_for(join_task, timeout=5)
            assert joined.status_code == 201
            entry_id = UUID(joined.json()["id"])

            _revoke(revoker, fixture)
            rejected = await client.post(
                "/v1/waitlist",
                json={
                    "offering_id": str(fixture.offering_id),
                    "subject_party_id": str(fixture.subject_party_id),
                },
                headers={
                    "Authorization": "Bearer represented",
                    "Idempotency-Key": f"waitlist-after-revoke-{uuid4().hex}",
                },
            )
            assert rejected.status_code == 403
            assert rejected.json()["error"]["code"] == "party_authority_required"

        persisted = admin_conn.execute(
            """
            SELECT organization_id, offering_id, subject_party_id, status, revision
            FROM request_engine.waitlist_entries
            WHERE id = %s
            """,
            (entry_id,),
        ).fetchone()
        assert persisted == (
            fixture.organization_id,
            fixture.offering_id,
            fixture.subject_party_id,
            "active",
            1,
        )
    finally:
        if not blocker.closed:
            blocker.rollback()
        if not revoker.closed:
            revoker.rollback()
        blocker.close()
        revoker.close()
