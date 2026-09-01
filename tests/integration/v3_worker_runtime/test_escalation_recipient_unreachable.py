"""PostgreSQL proof: recipient_unreachable escalates through the real worker.

docs/v3/36 section 4 ``recipient_unreachable``: when the pinned contact point
dies, the production dispatch surface (real ``ScheduledAction`` row, real
``CommunicationDeliveryScheduledHandler``) resolves
``RecipientChannelUnavailable``, closes the task with its task_failed fact and
escalates to the next policy channel — no durable poison, no delivery row.
"""

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
async def test_dead_pinned_contact_point_escalates_instead_of_poisoning(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "unreachable-worker")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    phone = world.new_contact_point(admin_conn, org, party, "phone")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="pending",
    )
    await worker.schedule_dispatch_action(app_session_factory, org, task)

    admin_conn.execute(
        "UPDATE request_engine.party_contact_points SET active = false WHERE id = %s",
        (whatsapp,),
    )
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
    assert children[0]["contact_point_id"] == phone
    assert children[0]["status"] == "pending"
    ledger = actions.ledger_rows(admin_conn, org, task)
    assert ledger == [
        {
            "trigger": "recipient_unreachable",
            "from_channel": "whatsapp",
            "to_channel": "sms",
            "ordinal": 1,
            "failure_class": "recipient_channel_unreachable",
            "child_task_id": children[0]["id"],
        }
    ]
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["recipient_channel_unreachable"]
    assert len(actions.outbox_payloads(admin_conn, org, "communication.task_escalated.v1")) == 1
    assert (
        world.scalar(
            admin_conn,
            "SELECT count(*) FROM request_engine.communication_deliveries"
            " WHERE communication_task_id = %s",
            task,
        )
        == 0
    )
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
            children[0]["id"],
        )
        == 1
    )
    assert admin_conn.execute(
        """
        SELECT count(*) FROM request_engine.outbox_messages
        WHERE organization_id = %s AND payload->>'reason' = 'delivery_configuration_invalid'
        """,
        (org,),
    ).fetchone() == (0,)
