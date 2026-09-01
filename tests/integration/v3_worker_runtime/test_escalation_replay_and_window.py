"""PostgreSQL proofs: escalation replay no-op and deadline-missed window.

docs/v3/40 T3 (b) + (f): replaying the same escalation decision is a no-op
(one child, one ledger row, one outbox fact), and a delivery_deadline_missed
escalation creates the child with one workable delivery window even though
the parent deadline already passed — reaching the patient after a missed
deadline is the point of the trigger.
"""

from datetime import UTC, datetime, timedelta

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.platform.db.session import SessionFactory

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_escalation_replay_is_a_no_op(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "step-b")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    sms = world.new_contact_point(admin_conn, org, party, "phone")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="failed",
    )
    world.new_attempting_delivery(admin_conn, org, task, channel="whatsapp")

    first = await actions.run_escalation(app_session_factory, org, task)
    second = await actions.run_escalation(app_session_factory, org, task)

    assert first.state == "escalated"
    assert second.state == "no_op"
    assert second.child_task_id is None
    children = actions.child_tasks(admin_conn, org, task)
    assert len(children) == 1
    assert children[0]["contact_point_id"] == sms
    assert children[0]["dedupe_key"] == f"communication:escalation:{task}:sms:1:v1"
    assert len(actions.ledger_rows(admin_conn, org, task)) == 1
    assert len(actions.outbox_payloads(admin_conn, org, "communication.task_escalated.v1")) == 1


@pytest.mark.asyncio
async def test_deadline_missed_escalation_gets_a_workable_delivery_window(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "step-f")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    expired = datetime.now(UTC) - timedelta(minutes=5)
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="failed",
        expires_at=expired,
    )

    outcome = await actions.run_escalation(
        app_session_factory,
        org,
        task,
        trigger="delivery_deadline_missed",
        failure_class="delivery_deadline_exceeded",
    )

    assert outcome.state == "escalated"
    children = actions.child_tasks(admin_conn, org, task)
    assert len(children) == 1
    child = children[0]
    assert child["contact_point_id"] == whatsapp
    assert child["status"] == "pending"
    assert child["expires_at"] is not None
    assert child["expires_at"] > datetime.now(UTC)
    ledger = actions.ledger_rows(admin_conn, org, task)
    assert ledger[0]["trigger"] == "delivery_deadline_missed"
    assert ledger[0]["failure_class"] == "delivery_deadline_exceeded"
    assert ledger[0]["from_channel"] == "whatsapp"
