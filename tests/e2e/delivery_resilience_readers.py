"""Durable delivery-row builders and read oracles (task/delivery/action state,
outbox event counts) for the e2e communication delivery suites."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

from . import operational_support as support


def new_delivery(
    conn: support.PgConnection,
    organization_id: UUID,
    task_id: UUID,
    *,
    status: str,
) -> UUID:
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_deliveries (
            organization_id, communication_task_id, attempt_no, channel,
            provider_key, provider_idempotency_key, provider_message_id,
            status, result_data
        ) VALUES (%s, %s, 1, 'email', 'provider-a', %s, %s, %s, '{}'::jsonb)
        RETURNING id
        """,
        (
            organization_id,
            task_id,
            f"communication:{task_id}:attempt:1",
            f"msg-{uuid4().hex}",
            status,
        ),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def delivery_id_for(conn: support.PgConnection, task_id: UUID) -> UUID:
    row = conn.execute(
        """
        SELECT id FROM request_engine.communication_deliveries
        WHERE communication_task_id = %s
        """,
        (task_id,),
    ).fetchone()
    assert row is not None
    return cast(UUID, row[0])


def task_status(conn: support.PgConnection, row_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def delivery_status(conn: support.PgConnection, row_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.communication_deliveries WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def action_status(conn: support.PgConnection, row_id: UUID) -> str:
    row = conn.execute(
        "SELECT status FROM request_engine.scheduled_actions WHERE id = %s",
        (row_id,),
    ).fetchone()
    assert row is not None
    return cast(str, row[0])


def event_count(
    conn: support.PgConnection,
    organization_id: UUID,
    event_type: str,
    aggregate_id: UUID,
) -> int:
    row = conn.execute(
        """
        SELECT count(*)
        FROM request_engine.outbox_messages
        WHERE organization_id = %s AND event_type = %s AND aggregate_id = %s
        """,
        (organization_id, event_type, aggregate_id),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])
