"""PostgreSQL proofs: the reconciliation deadline gate escalates end-to-end.

docs/v3/36 section 3 + section 4: a past-deadline ambiguous delivery observed
by the production reconcile surface (real ``ScheduledAction`` row, real
``CommunicationDeliveryScheduledHandler``) closes via
``close_task_failed_and_escalate``; the escalation step creates the next
channel child while channels remain, and closes the lineage terminal
``unreachable`` once the ladder is exhausted.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

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


def _expired_world(
    admin_conn: world.PgConnection, label: str, policy: dict[str, object]
) -> tuple[UUID, UUID, UUID, UUID]:
    org = world.new_organization(admin_conn, label)
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    world.new_contact_point(admin_conn, org, party, "phone")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=policy,
        contact_point_id=whatsapp,
        status="delivering",
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    delivery = world.new_attempting_delivery(admin_conn, org, task, channel="whatsapp")
    return org, task, delivery, whatsapp


def _driven_stack(
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> tuple[PostgresScheduledActionWorker, CommunicationDeliveryScheduledHandler]:
    scheduler = PostgresScheduledActionWorker(worker_session_factory)
    return scheduler, CommunicationDeliveryScheduledHandler(app_session_factory, scheduler, {})


@pytest.mark.asyncio
async def test_past_deadline_reconcile_closes_task_and_escalates_to_next_channel(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    org, task, delivery, _whatsapp = _expired_world(admin_conn, "deadline-reconcile", world.POLICY)
    await worker.schedule_reconcile_action(app_session_factory, org, delivery)
    scheduler, handler = _driven_stack(app_session_factory, worker_session_factory)
    assert await worker.claim_and_drive(scheduler, handler, delivery) is True

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
    assert children[0]["status"] == "pending"
    ledger = actions.ledger_rows(admin_conn, org, task)
    assert ledger[0]["trigger"] == "delivery_deadline_missed"
    assert ledger[0]["from_channel"] == "whatsapp"
    assert ledger[0]["to_channel"] == "sms"
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["delivery_deadline_exceeded"]


@pytest.mark.asyncio
async def test_past_deadline_reconcile_with_exhausted_ladder_closes_lineage_unreachable(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
    worker_session_factory: SessionFactory,
) -> None:
    single_channel: dict[str, object] = {
        "channels": ["whatsapp"],
        "provider_key": "webhook",
    }
    org, task, delivery, _whatsapp = _expired_world(
        admin_conn, "deadline-reconcile-end", single_channel
    )
    await worker.schedule_reconcile_action(app_session_factory, org, delivery)
    scheduler, handler = _driven_stack(app_session_factory, worker_session_factory)
    assert await worker.claim_and_drive(scheduler, handler, delivery) is True

    assert (
        world.scalar(
            admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task,
        )
        == "failed"
    )
    assert actions.child_tasks(admin_conn, org, task) == []
    assert actions.ledger_rows(admin_conn, org, task) == []
    terminals = actions.outbox_payloads(admin_conn, org, "communication.lineage_unreachable.v1")
    assert len(terminals) == 1
    assert terminals[0]["reason"] == "unreachable"
    assert terminals[0]["root_task_id"] == str(task)
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["delivery_deadline_exceeded"]
