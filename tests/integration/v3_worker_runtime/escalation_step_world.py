"""Shared PostgreSQL world for the S3 escalation step proofs (docs/v3/40 T3/T4)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, LiteralString, cast
from uuid import UUID, uuid4

import psycopg
from psycopg import Connection

PgConnection = Connection[Any]

POLICY: dict[str, object] = {
    "channels": ["whatsapp", "sms", "email"],
    "provider_key": "webhook",
    "retry_after_seconds": 30,
    "reconcile_after_seconds": 30,
}


def new_organization(conn: PgConnection, label: str) -> UUID:
    suffix = uuid4().hex
    row = conn.execute(
        "INSERT INTO request_engine.organizations (organization_key, display_name)"
        " VALUES (%s, %s) RETURNING id",
        (f"esc-{label}-{suffix}", f"Escalation {label}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_party(conn: PgConnection, organization_id: UUID) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.parties (organization_id, party_kind, display_name)"
        " VALUES (%s, 'person', %s) RETURNING id",
        (organization_id, f"Recipient {uuid4().hex[:8]}"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_contact_point(
    conn: PgConnection,
    organization_id: UUID,
    party_id: UUID,
    channel: str,
) -> UUID:
    row = conn.execute(
        "INSERT INTO request_engine.party_contact_points ("
        " organization_id, party_id, channel, normalized_value, verified)"
        " VALUES (%s, %s, %s, %s, true) RETURNING id",
        (organization_id, party_id, channel, f"{channel}-{uuid4().hex[:8]}@example.test"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_task(
    conn: PgConnection,
    organization_id: UUID,
    party_id: UUID,
    *,
    policy: dict[str, object],
    contact_point_id: UUID | None,
    status: str = "pending",
    expires_at: datetime | None = None,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id, purpose,
            template_key, template_version, render_context, channel_policy,
            dedupe_key, status, expires_at
        ) VALUES (%s, %s, %s, 'appointment_confirmation', 'booking-confirmed', 1,
                  '{}'::jsonb, %s::jsonb, %s, %s, %s)
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_point_id,
            json.dumps(policy),
            f"esc-task:{uuid4().hex}",
            status,
            expires_at,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_attempting_delivery(
    conn: PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    channel: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, status, result_data
        ) VALUES (%s, %s, 1, %s, 'webhook', %s, 'attempting', '{}'::jsonb)
        RETURNING id
        """,
        (organization_id, task_id, channel, f"communication:{task_id}:attempt:1"),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def scalar(conn: PgConnection, query: LiteralString, *params: Any) -> Any:
    row = conn.execute(query, params).fetchone()
    assert row is not None
    return row[0]


def connect() -> PgConnection:
    return psycopg.connect(
        f"host={os.environ.get('PGHOST', '127.0.0.1')}"
        f" port={os.environ.get('PGPORT', '5432')}"
        f" dbname={os.environ.get('PGDATABASE', 'request_engine_v3')}"
        f" user={os.environ.get('PGUSER', 'request_engine')}"
        f" password={os.environ.get('PGPASSWORD', 'request_engine')}"
    )
