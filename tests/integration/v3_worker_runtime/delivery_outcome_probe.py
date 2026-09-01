"""Authoritative-state probes for provider-event delivery outcome proofs."""

from __future__ import annotations

from typing import Any, LiteralString, cast
from uuid import UUID

from psycopg import Connection

PgConnection = Connection[Any]


def _scalar(conn: PgConnection, sql: LiteralString, params: tuple[object, ...]) -> object:
    row = conn.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def task_status(conn: PgConnection, task_id: UUID) -> str:
    return cast(
        str,
        _scalar(
            conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            (task_id,),
        ),
    )


def delivery_status(conn: PgConnection, delivery_id: UUID) -> str:
    return cast(
        str,
        _scalar(
            conn,
            "SELECT status FROM request_engine.communication_deliveries WHERE id = %s",
            (delivery_id,),
        ),
    )


def event_row(conn: PgConnection, event_id: UUID) -> tuple[str, str | None]:
    row = conn.execute(
        "SELECT status, last_error_class FROM request_engine.provider_events WHERE id = %s",
        (event_id,),
    ).fetchone()
    assert row is not None
    return (cast(str, row[0]), cast(str | None, row[1]))


def outbox_count(
    conn: PgConnection,
    organization_id: UUID,
    event_type: str,
    task_id: UUID,
) -> int:
    return cast(
        int,
        _scalar(
            conn,
            """
            SELECT count(*)
            FROM request_engine.outbox_messages
            WHERE organization_id = %s AND event_type = %s AND aggregate_id = %s
            """,
            (organization_id, event_type, task_id),
        ),
    )
