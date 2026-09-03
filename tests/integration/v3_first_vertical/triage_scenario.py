from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]


def uuid_row(
    conn: PgConnection,
    sql: LiteralString,
    params: tuple[object, ...] = (),
) -> UUID:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def create_organization(conn: PgConnection) -> UUID:
    suffix = uuid4().hex
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s) RETURNING id
        """,
        (f"triage-{suffix}", f"Triage clinic {suffix}"),
    )


def create_principal(conn: PgConnection, organization_id: UUID) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.principals (
            organization_id, principal_kind, external_subject
        ) VALUES (%s, 'human', %s) RETURNING id
        """,
        (organization_id, f"operator-{uuid4().hex}"),
    )


def create_party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s) RETURNING id
        """,
        (organization_id, name),
    )


def create_queue(conn: PgConnection, organization_id: UUID) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.service_queues (
            organization_id, queue_key, display_name
        ) VALUES (%s, %s, 'Walk-in triage') RETURNING id
        """,
        (organization_id, f"triage-{uuid4().hex}"),
    )


def create_entry(
    conn: PgConnection,
    organization_id: UUID,
    queue_id: UUID,
    subject_id: UUID,
    admitted_at: str,
) -> UUID:
    return uuid_row(
        conn,
        """
        INSERT INTO request_engine.queue_entries (
            organization_id, service_queue_id, subject_party_id,
            arrived_at, admitted_at
        ) VALUES (%s, %s, %s, %s::timestamptz, %s::timestamptz)
        RETURNING id
        """,
        (organization_id, queue_id, subject_id, admitted_at, admitted_at),
    )


def create_world(conn: PgConnection, count: int = 3) -> tuple[UUID, UUID, UUID, tuple[UUID, ...]]:
    organization_id = create_organization(conn)
    principal_id = create_principal(conn, organization_id)
    queue_id = create_queue(conn, organization_id)
    entries = tuple(
        create_entry(
            conn,
            organization_id,
            queue_id,
            create_party(conn, organization_id, f"Patient {index}"),
            f"2026-09-02 1{index}:00:00+00",
        )
        for index in range(count)
    )
    return organization_id, principal_id, queue_id, entries
