"""Shared support for the S0b party registry PostgreSQL proofs."""

import asyncio
import os
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection

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


def lock_audit_barrier(blocker: PgConnection) -> None:
    """Hold the audit append point so a command transaction stays uncommitted."""

    blocker.execute("LOCK TABLE request_engine.audit_records IN ACCESS EXCLUSIVE MODE")


async def wait_until_query_blocked(
    observer: PgConnection, query_pattern: str, failure: str
) -> None:
    """Deterministic race synchronization: poll pg_stat_activity for a lock waiter."""

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
            (query_pattern,),
        ).fetchone()
        assert row is not None
        if int(row[0]) >= 1:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(failure)


def document_rows(conn: PgConnection, organization_id: UUID, cedula: str) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT party_id, kind, normalized_value, active"
        " FROM request_engine.party_identity_documents"
        " WHERE organization_id = %s AND kind = 'cedula' AND normalized_value = %s",
        (organization_id, cedula),
    ).fetchall()


def party_rows(conn: PgConnection, organization_id: UUID) -> list[tuple[Any, ...]]:
    return conn.execute(
        "SELECT id, display_name FROM request_engine.parties WHERE organization_id = %s",
        (organization_id,),
    ).fetchall()


def contact_point_row(
    conn: PgConnection, organization_id: UUID, contact_point_id: UUID
) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT verified, source_kind, active"
        " FROM request_engine.party_contact_points"
        " WHERE organization_id = %s AND id = %s",
        (organization_id, contact_point_id),
    ).fetchone()
    assert row is not None
    return row


def audit_rows(conn: PgConnection, organization_id: UUID, capability: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT details FROM request_engine.audit_records"
        " WHERE organization_id = %s AND command_name = %s",
        (organization_id, capability),
    ).fetchall()
    return [row[0] for row in rows]


def outbox_rows(conn: PgConnection, organization_id: UUID, event_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT payload FROM request_engine.outbox_messages"
        " WHERE organization_id = %s AND event_type = %s",
        (organization_id, event_type),
    ).fetchall()
    return [row[0] for row in rows]
