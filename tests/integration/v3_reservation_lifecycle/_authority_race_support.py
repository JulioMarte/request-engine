import asyncio
import os
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.errors import LockNotAvailable

PgConnection = Connection[Any]


def connect() -> PgConnection:
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = os.environ.get("PGPORT", "5432")
    database = os.environ.get("PGDATABASE", "request_engine_v3")
    user = os.environ.get("PGUSER", "request_engine")
    password = os.environ.get("PGPASSWORD", "request_engine")
    return psycopg.connect(
        f"host={host} port={port} dbname={database} user={user} password={password}"
    )


def create_representation(
    conn: PgConnection,
    *,
    organization_id: UUID,
    principal_id: UUID,
    party_id: UUID,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.representations (
            organization_id, principal_id, represented_party_id,
            authority_kind, scope_key, valid_from, valid_until
        ) VALUES (
            %s, %s, %s, 'delegated', 'appointments.manage',
            clock_timestamp() - interval '1 minute',
            clock_timestamp() + interval '1 day'
        )
        RETURNING id
        """,
        (organization_id, principal_id, party_id),
    ).fetchone()
    assert row is not None
    return row[0]


def lock_audit_barrier(conn: PgConnection) -> None:
    conn.execute("LOCK TABLE request_engine.audit_records IN ACCESS EXCLUSIVE MODE")


async def _wait_for_lock_query(observer: PgConnection, pattern: str, failure: str) -> None:
    deadline = asyncio.get_running_loop().time() + 5
    while asyncio.get_running_loop().time() < deadline:
        row = observer.execute(
            """
            SELECT count(*)
            FROM pg_stat_activity
            WHERE datname = current_database()
              AND pid <> pg_backend_pid()
              AND wait_event_type = 'Lock'
              AND query ILIKE %s
            """,
            (pattern,),
        ).fetchone()
        assert row is not None
        if int(row[0]) >= 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(failure)


async def wait_until_audit_blocked(observer: PgConnection) -> None:
    await _wait_for_lock_query(
        observer,
        "%INSERT INTO request_engine.audit_records%",
        "appointment command never reached the post-authority audit barrier",
    )


async def wait_until_authority_blocked(observer: PgConnection) -> None:
    await _wait_for_lock_query(
        observer,
        "%lock_current_party_authority%",
        "appointment command never blocked on the authority lock",
    )


def assert_revoke_blocked(
    revoker: PgConnection,
    *,
    organization_id: UUID,
    representation_id: UUID,
) -> None:
    revoker.execute("SET LOCAL lock_timeout = '250ms'")
    try:
        revoker.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, representation_id),
        )
    except LockNotAvailable:
        revoker.rollback()
        return
    revoker.rollback()
    raise AssertionError("Representation revoke was not blocked by appointment authority")


def begin_revoke(
    revoker: PgConnection,
    *,
    organization_id: UUID,
    representation_id: UUID,
) -> None:
    updated = revoker.execute(
        """
        UPDATE request_engine.representations
        SET status = 'revoked', revision = revision + 1
        WHERE organization_id = %s AND id = %s
        """,
        (organization_id, representation_id),
    )
    assert updated.rowcount == 1


def revoke_and_commit(
    revoker: PgConnection,
    *,
    organization_id: UUID,
    representation_id: UUID,
) -> None:
    begin_revoke(
        revoker,
        organization_id=organization_id,
        representation_id=representation_id,
    )
    revoker.commit()
