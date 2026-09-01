"""PostgreSQL proofs: escalation exhaustion and fatigue terminal facts."""

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.platform.db.session import SessionFactory

pytestmark = pytest.mark.postgres

TWO_CHANNEL_POLICY: dict[str, object] = {
    "channels": ["whatsapp", "sms"],
    "provider_key": "webhook",
    "retry_after_seconds": 30,
    "reconcile_after_seconds": 30,
}


@pytest.mark.asyncio
async def test_exhausted_ladder_closes_the_lineage_unreachable(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "terminal-d")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    world.new_contact_point(admin_conn, org, party, "phone")
    root = world.new_task(
        admin_conn,
        org,
        party,
        policy=TWO_CHANNEL_POLICY,
        contact_point_id=whatsapp,
        status="delivering",
    )
    root_delivery = world.new_attempting_delivery(admin_conn, org, root, channel="whatsapp")

    first = await actions.finalize_non_retryable_failure(app_session_factory, org, root_delivery)
    children = actions.child_tasks(admin_conn, org, root)
    assert first.task_terminal and len(children) == 1
    sms_delivery = world.new_attempting_delivery(
        admin_conn,
        org,
        children[0]["id"],
        channel="sms",
    )

    second = await actions.finalize_non_retryable_failure(
        app_session_factory,
        org,
        sms_delivery,
    )

    assert second.task_terminal
    assert len(actions.child_tasks(admin_conn, org, root)) == 1
    assert len(actions.child_tasks(admin_conn, org, children[0]["id"])) == 0
    assert len(actions.ledger_rows(admin_conn, org, root)) == 1
    terminals = actions.outbox_payloads(admin_conn, org, "communication.lineage_unreachable.v1")
    assert len(terminals) == 1
    assert terminals[0]["reason"] == "unreachable"
    assert terminals[0]["lineage_id"] == str(root)
    assert terminals[0]["root_task_id"] == str(root)
    assert terminals[0]["communication_task_id"] == str(children[0]["id"])
    for task_id in (root, children[0]["id"]):
        assert (
            world.scalar(
                admin_conn,
                "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
                task_id,
            )
            == "failed"
        )


@pytest.mark.asyncio
async def test_fatigue_guard_closes_the_lineage_without_a_child(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "terminal-e")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    policy: dict[str, object] = dict(TWO_CHANNEL_POLICY, max_contacts_per_subject_per_day=1)
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=policy,
        contact_point_id=whatsapp,
        status="delivering",
    )
    delivery = world.new_attempting_delivery(admin_conn, org, task, channel="whatsapp")

    finalized = await actions.finalize_non_retryable_failure(app_session_factory, org, delivery)

    assert finalized.task_terminal
    assert actions.child_tasks(admin_conn, org, task) == []
    assert actions.ledger_rows(admin_conn, org, task) == []
    terminals = actions.outbox_payloads(admin_conn, org, "communication.lineage_unreachable.v1")
    assert len(terminals) == 1
    assert terminals[0]["reason"] == "fatigue_limited"
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["provider_non_retryable_failure"]
