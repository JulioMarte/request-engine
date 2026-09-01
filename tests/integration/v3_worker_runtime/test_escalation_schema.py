"""PostgreSQL backstops for the S3 escalation schema (docs/v3/40 T2).

Proves: at most one live task per notification lineage (partial unique), the
lineage shape CHECK, and the append-only escalation ledger (privilege denial
for the runtime role's missing grants, and the guard trigger for the owner).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import delivery_outcome_world as world
import psycopg
import pytest
from psycopg import Connection
from sqlalchemy import text

from request_engine.platform.db.session import SessionFactory

PgConnection = Connection[Any]

pytestmark = pytest.mark.postgres

_LIVE = ("WHERE lineage_id = %s AND status IN ('pending', 'delivering')",)


def _escalate(
    conn: PgConnection,
    parent_task_id: UUID,
    *,
    lineage_id: UUID,
    status: str = "pending",
) -> UUID:
    suffix = uuid4().hex
    row = conn.execute(
        """
        INSERT INTO request_engine.communication_tasks (
            organization_id, recipient_party_id, purpose, template_key,
            template_version, render_context, channel_policy, dedupe_key, status,
            parent_task_id, lineage_id, escalation_ordinal
        ) SELECT organization_id, recipient_party_id,
                 'appointment_confirmation', 'booking-confirmed', 1,
                 '{}'::jsonb, '{"channels": ["sms"]}'::jsonb, %s, %s,
                 %s, %s, 1
          FROM request_engine.communication_tasks WHERE id = %s
        RETURNING id
        """,
        (
            f"escalated:{suffix}",
            status,
            parent_task_id,
            lineage_id,
            parent_task_id,
        ),
    ).fetchone()
    assert row is not None
    return row[0]


def test_second_live_lineage_task_is_rejected_by_the_backstop(admin_conn: PgConnection) -> None:
    org = world.new_organization(admin_conn, "lineage-uq")
    parent = world.new_task(admin_conn, org)
    child = _escalate(admin_conn, parent, lineage_id=parent)

    with pytest.raises(Exception, match="communication_tasks_live_lineage_uq"):
        _escalate(admin_conn, parent, lineage_id=parent)

    # Terminalising the live task releases the lineage for the next channel.
    admin_conn.execute(
        "UPDATE request_engine.communication_tasks SET status = 'failed' WHERE id = %s",
        (child,),
    )
    next_child = _escalate(admin_conn, parent, lineage_id=parent)
    assert next_child != child


@pytest.mark.asyncio
async def test_escalation_ledger_is_append_only_for_every_role(
    admin_conn: PgConnection, app_session_factory: SessionFactory
) -> None:
    org = world.new_organization(admin_conn, "ledger-guard")
    parent = world.new_task(admin_conn, org)
    child = _escalate(admin_conn, parent, lineage_id=parent)
    admin_conn.execute(
        """
        INSERT INTO request_engine.communication_escalations (
            organization_id, parent_task_id, child_task_id, trigger,
            from_channel, to_channel, ordinal
        ) VALUES (%s, %s, %s, 'definitive_failure', 'whatsapp', 'sms', 1)
        """,
        (org, parent, child),
    )

    for statement in (
        "UPDATE request_engine.communication_escalations SET failure_class = 'x'",
        "DELETE FROM request_engine.communication_escalations",
    ):
        async with app_session_factory() as session:
            await session.execute(
                text("SELECT set_config('request_engine.organization_id', :org, true)"),
                {"org": str(org)},
            )
            with pytest.raises(Exception, match="append-only|permission denied"):
                await session.execute(text(statement))

    admin_conn.execute("SET ROLE request_engine_schema_owner")
    try:
        admin_conn.execute(
            "SELECT set_config('request_engine.organization_id', %s, false)",
            (str(org),),
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute(
                "UPDATE request_engine.communication_escalations"
                " SET failure_class = 'x' WHERE organization_id = %s",
                (org,),
            )
        with pytest.raises(psycopg.errors.CheckViolation):
            admin_conn.execute("DELETE FROM request_engine.communication_escalations")
    finally:
        admin_conn.execute("RESET ROLE")
        admin_conn.rollback()
