import json
from datetime import datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

from psycopg import Connection

PgConnection = Connection[Any]

CHANNEL_POLICY = {
    "channels": ["email"],
    "provider_key": "provider-a",
    "reconcile_after_seconds": 30,
    "retry_after_seconds": 30,
}


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


def new_contact_point(conn: PgConnection, organization_id: UUID, party_id: UUID) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.party_contact_points (
            organization_id, party_id, channel, normalized_value, verified
        ) VALUES (%s, %s, 'email', %s, true)
        RETURNING id
        """,
        (organization_id, party_id, f"{uuid4().hex}@example.test"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_task(
    conn: PgConnection,
    organization_id: UUID,
    *,
    party_id: UUID,
    contact_point_id: UUID | None,
    expires_at: datetime,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status, expires_at
        ) VALUES (
            %s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, 'pending', %s
        )
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_point_id,
            json.dumps(CHANNEL_POLICY),
            f"module-task:{uuid4().hex}",
            expires_at,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def fetch_one(conn: PgConnection, query: LiteralString, *params: Any) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def outbox_payloads(
    conn: PgConnection,
    organization_id: UUID,
    event_type: str,
) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        SELECT payload
        FROM request_engine.outbox_messages
        WHERE organization_id = %s AND event_type = %s
        ORDER BY created_at, id
        """,
        (organization_id, event_type),
    ).fetchall()
    return [cast(dict[str, object], row[0]) for row in rows]
