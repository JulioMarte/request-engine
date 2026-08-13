import os
from typing import Any, cast
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import Connection
from psycopg.errors import LockNotAvailable

PgConnection = Connection[Any]


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


def _uuid_row(conn: PgConnection, sql: str, params: tuple[object, ...]) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


@pytest.mark.integration
@pytest.mark.postgres
def test_mutation_authority_lock_serializes_concurrent_revocation(
    admin_conn: PgConnection,
) -> None:
    suffix = uuid4().hex
    organization_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, 'Authority linearization')
        RETURNING id
        """,
        (f"authority-linearization-{suffix}",),
    )
    principal_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'agent', %s)
        RETURNING id
        """,
        (organization_id, f"agent-{suffix}"),
    )
    party_id = _uuid_row(
        admin_conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', 'Protected Party')
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
            scope_key
        ) VALUES (%s, %s, %s, 'delegated', 'appointments.manage')
        RETURNING id
        """,
        (organization_id, principal_id, party_id),
    )

    authorizing = _connect()
    revoking = _connect()
    try:
        authorizing.execute("BEGIN")
        locked = authorizing.execute(
            """
            SELECT representation_id
            FROM request_engine.lock_current_party_authority(%s, %s, %s, %s)
            """,
            (organization_id, principal_id, party_id, "appointments.manage"),
        ).fetchone()
        assert locked == (representation_id,)

        revoking.execute("BEGIN")
        revoking.execute("SET LOCAL lock_timeout = '200ms'")
        with pytest.raises(LockNotAvailable):
            revoking.execute(
                """
                UPDATE request_engine.representations
                SET status = 'revoked', revision = revision + 1
                WHERE organization_id = %s AND id = %s
                """,
                (organization_id, representation_id),
            )
        revoking.rollback()

        authorizing.commit()

        revoking.execute("BEGIN")
        revoking.execute(
            """
            UPDATE request_engine.representations
            SET status = 'revoked', revision = revision + 1
            WHERE organization_id = %s AND id = %s
            """,
            (organization_id, representation_id),
        )
        revoking.commit()

        resolved = admin_conn.execute(
            """
            SELECT representation_id
            FROM request_engine.resolve_current_party_authority(%s, %s, %s, %s)
            """,
            (organization_id, principal_id, party_id, "appointments.manage"),
        ).fetchone()
        assert resolved is None
    finally:
        if not authorizing.closed:
            authorizing.rollback()
        if not revoking.closed:
            revoking.rollback()
        authorizing.close()
        revoking.close()
