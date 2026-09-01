"""Durable communication task/action world builders for the e2e delivery
suites (direct SQL establishes only valid prerequisites)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from uuid import UUID, uuid4

from . import operational_support as support
from .delivery_resilience_world import PAST, POLICY


def new_task(conn: support.PgConnection, organization_id: UUID, *, status: str = "pending") -> UUID:
    party_id = support.new_party(conn, organization_id, f"Recipient {uuid4().hex[:8]}")
    contact_id = support.new_contact_point(conn, organization_id, party_id, "delivery")
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, contact_point_id,
            purpose, template_key, template_version, render_context,
            channel_policy, dedupe_key, status
        ) VALUES (%s, %s, %s, 'confirmation', 'booking-confirmed', 1,
            '{}'::jsonb, %s::jsonb, %s, %s)
        RETURNING id
        """,
        (
            organization_id,
            party_id,
            contact_id,
            json.dumps(POLICY),
            f"delivery-e2e:{uuid4().hex}",
            status,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def new_action(
    conn: support.PgConnection,
    organization_id: UUID,
    *,
    action_type: str,
    subject_kind: str,
    subject_id: UUID,
    payload: dict[str, str],
    execute_at: datetime | None = None,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.scheduled_actions (
            organization_id, owner_module, action_type, action_version,
            subject_kind, subject_id, payload, dedupe_key,
            execute_at, next_attempt_at
        ) VALUES (%s, 'communications', %s, 1, %s, %s, %s::jsonb, %s, %s, %s)
        RETURNING id
        """,
        (
            organization_id,
            action_type,
            subject_kind,
            subject_id,
            json.dumps(payload),
            f"communications-e2e:{action_type}:{uuid4().hex}",
            execute_at or PAST,
            execute_at or PAST,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def dispatch(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    payload_task_id: UUID | None = None,
) -> UUID:
    return new_action(
        conn,
        organization_id,
        action_type="dispatch_task",
        subject_kind="CommunicationTask",
        subject_id=task_id,
        payload={"communication_task_id": str(payload_task_id or task_id)},
    )


def reconcile(
    conn: support.PgConnection,
    organization_id: UUID,
    delivery_id: UUID,
) -> UUID:
    return new_action(
        conn,
        organization_id,
        action_type="reconcile_delivery",
        subject_kind="CommunicationDelivery",
        subject_id=delivery_id,
        payload={"delivery_id": str(delivery_id)},
    )
