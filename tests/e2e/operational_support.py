from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection
from psycopg.conninfo import make_conninfo

PgConnection = Connection[Any]


class RuntimeCredentialsLike(Protocol):
    role_name: str
    password: str
    database_url: str


def runtime_dsn(credentials: RuntimeCredentialsLike) -> str:
    return make_conninfo(
        host=os.environ.get("PGHOST", "127.0.0.1"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "request_engine_v3"),
        user=credentials.role_name,
        password=credentials.password,
    )


def runtime_conn(credentials: RuntimeCredentialsLike) -> PgConnection:
    return psycopg.connect(runtime_dsn(credentials), autocommit=True)


def new_org(conn: PgConnection, prefix: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.organizations (organization_key, display_name)
        VALUES (%s, %s)
        RETURNING id
        """,
        (f"{prefix}-{uuid4().hex}", f"{prefix} organization"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_party(conn: PgConnection, organization_id: UUID, name: str) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.parties (organization_id, party_kind, display_name)
        VALUES (%s, 'person', %s)
        RETURNING id
        """,
        (organization_id, name),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_contact_point(
    conn: PgConnection,
    organization_id: UUID,
    party_id: UUID,
    suffix: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'email', %s, true)
        RETURNING id
        """,
        (organization_id, party_id, f"{suffix}-{uuid4().hex}@example.test"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def insert_scheduled_action(
    conn: PgConnection,
    organization_id: UUID,
    *,
    when: datetime,
    max_attempts: int = 8,
    status: str = "pending",
    claim_token: UUID | None = None,
    lease_until: datetime | None = None,
    attempt_count: int = 0,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id,
            owner_module,
            action_type,
            subject_kind,
            payload,
            dedupe_key,
            execute_at,
            next_attempt_at,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts
        ) VALUES (
            %s, 'e2e', 'probe', 'test', '{}'::jsonb, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            f"e2e-scheduled-{uuid4().hex}",
            when,
            when,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def insert_outbox_message(
    conn: PgConnection,
    organization_id: UUID,
    *,
    when: datetime,
    max_attempts: int = 12,
    status: str = "pending",
    claim_token: UUID | None = None,
    lease_until: datetime | None = None,
    attempt_count: int = 0,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.outbox_messages (
            organization_id,
            event_type,
            payload,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts,
            next_attempt_at
        ) VALUES (
            %s, 'e2e.probe.v1', '{}'::jsonb, %s, %s, %s, %s, %s, %s
        )
        RETURNING id
        """,
        (
            organization_id,
            status,
            claim_token,
            lease_until,
            attempt_count,
            max_attempts,
            when,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def claim_scheduled(conn: PgConnection, limit: int) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            "SELECT * FROM request_cmd.claim_scheduled_actions(%s, %s)",
            (limit, timedelta(seconds=30)),
        ).fetchall()
    )


def claim_outbox(conn: PgConnection, limit: int) -> list[tuple[Any, ...]]:
    return list(
        conn.execute(
            "SELECT * FROM request_cmd.claim_outbox_messages(%s, %s)",
            (limit, timedelta(seconds=30)),
        ).fetchall()
    )
