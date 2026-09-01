"""PostgreSQL proof: the dispatch deadline gate escalates end-to-end.

docs/v3/36 section 3 + section 4: a past-deadline task observed by the
production dispatch surface (real ``ScheduledAction`` row, real
``CommunicationDeliveryScheduledHandler``) closes via
``close_task_failed_and_escalate`` and fires the escalation step: the child
re-attempts the pinned channel with one fresh workable window.
"""

from datetime import UTC, datetime, timedelta

import escalation_step_actions as actions
import escalation_step_world as world
import escalation_worker_actions as worker
import pytest

from request_engine.modules.communications.adapters.worker.scheduled_delivery import (
    CommunicationDeliveryScheduledHandler,
)
from request_engine.platform.db.session import SessionFactory
from request_engine.platform.scheduling.postgres import PostgresScheduledActionWorker

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_past_deadline_dispatch_closes_task_and_escalates(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "deadline-dispatch")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="pending",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await worker.schedule_dispatch_action(app_session_factory, org, task)

    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    handler = CommunicationDeliveryScheduledHandler(app_session_factory, scheduler, {})
    assert await worker.claim_and_drive(scheduler, handler, task) is True

    assert (
        world.scalar(
            admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task,
        )
        == "failed"
    )
    children = actions.child_tasks(admin_conn, org, task)
    assert len(children) == 1
    child = children[0]
    assert child["contact_point_id"] == whatsapp
    assert child["status"] == "pending"
    assert child["expires_at"] is not None
    assert child["expires_at"] > datetime.now(UTC)
    ledger = actions.ledger_rows(admin_conn, org, task)
    assert ledger == [
        {
            "trigger": "delivery_deadline_missed",
            "from_channel": "whatsapp",
            "to_channel": "whatsapp",
            "ordinal": 1,
            "failure_class": "expired_before_delivery",
            "child_task_id": child["id"],
        }
    ]
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["expired_before_delivery"]
    assert (
        world.scalar(
            admin_conn,
            """
            SELECT count(*) FROM request_engine.scheduled_actions
            WHERE organization_id = %s AND owner_module = 'communications'
              AND action_type = 'dispatch_task' AND subject_id = %s
              AND status = 'pending'
            """,
            org,
            child["id"],
        )
        == 1
    )
