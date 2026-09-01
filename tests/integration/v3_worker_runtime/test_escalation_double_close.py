"""PostgreSQL proof: a repeated terminal close emits no duplicate fact.

docs/v3/36 section 4 discipline: the same task's failure triggered twice —
first through the deadline gate (``prepare_reconciliation``), then through a
non-retryable fenced finalize — produces exactly one
``communication.task_failed.v1`` fact and one revision bump; the second
escalation step runs but is a no-op on the live lineage.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    prepare_reconciliation,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

pytestmark = pytest.mark.postgres


def _task_row(conn: world.PgConnection, task: object) -> tuple[Any, ...]:
    row = conn.execute(
        "SELECT status, revision FROM request_engine.communication_tasks WHERE id = %s",
        (task,),
    ).fetchone()
    assert row is not None
    return tuple(row)


@pytest.mark.asyncio
async def test_second_trigger_on_failed_task_appends_no_duplicate_fact(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "double-close")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    world.new_contact_point(admin_conn, org, party, "phone")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="delivering",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    delivery = world.new_attempting_delivery(admin_conn, org, task, channel="whatsapp")

    async with tenant_transaction(app_session_factory, org) as session:
        first = await prepare_reconciliation(session, organization_id=org, delivery_id=delivery)
    assert first.skip_reason == "task_expired"
    assert len(actions.child_tasks(admin_conn, org, task)) == 1
    revision = _task_row(admin_conn, task)[1]
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["delivery_deadline_exceeded"]

    second = await actions.finalize_non_retryable_failure(app_session_factory, org, delivery)

    assert second.task_terminal is True
    assert _task_row(admin_conn, task) == ("failed", revision)
    assert actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1") == failures
    assert len(actions.child_tasks(admin_conn, org, task)) == 1
    assert len(actions.ledger_rows(admin_conn, org, task)) == 1
    assert len(actions.outbox_payloads(admin_conn, org, "communication.task_escalated.v1")) == 1
    assert actions.outbox_payloads(admin_conn, org, "communication.lineage_unreachable.v1") == []
