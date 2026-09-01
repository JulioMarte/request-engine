"""PostgreSQL proof: definitive failure escalates to the next policy channel.

docs/v3/40 T3 (a): a definitive (non-retryable) provider failure on the first
policy channel closes the parent terminally and creates exactly one child
task on the NEXT policy channel — pinned to a verified contact point, wired
into the existing dispatch machinery, with an append-only ledger row, the
``communication.task_escalated.v1`` fact, and the parent failed. The child
dispatches on its own channel through the unchanged prepare surface.
"""

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    prepare_dispatch,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

pytestmark = pytest.mark.postgres


@pytest.mark.asyncio
async def test_definitive_failure_escalates_to_next_policy_channel(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "step-a")
    party = world.new_party(admin_conn, org)
    whatsapp = world.new_contact_point(admin_conn, org, party, "whatsapp")
    sms = world.new_contact_point(admin_conn, org, party, "phone")
    task = world.new_task(
        admin_conn,
        org,
        party,
        policy=world.POLICY,
        contact_point_id=whatsapp,
        status="delivering",
    )
    delivery = world.new_attempting_delivery(admin_conn, org, task, channel="whatsapp")

    finalized = await actions.finalize_non_retryable_failure(app_session_factory, org, delivery)

    assert finalized.task_terminal
    children = actions.child_tasks(admin_conn, org, task)
    assert len(children) == 1
    child = children[0]
    assert child["status"] == "pending"
    assert child["contact_point_id"] == sms
    assert child["parent_task_id"] == task
    assert child["lineage_id"] == task
    assert child["escalation_ordinal"] == 1
    assert child["recipient_party_id"] == party
    assert child["dedupe_key"] == f"communication:escalation:{task}:sms:1:v1"
    assert (
        world.scalar(
            admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task,
        )
        == "failed"
    )

    ledger = actions.ledger_rows(admin_conn, org, task)
    assert ledger == [
        {
            "trigger": "definitive_failure",
            "from_channel": "whatsapp",
            "to_channel": "sms",
            "ordinal": 1,
            "failure_class": "provider_non_retryable_failure",
            "child_task_id": child["id"],
        }
    ]
    assert actions.outbox_payloads(admin_conn, org, "communication.task_escalated.v1") == [
        {
            "parent_task_id": str(task),
            "child_task_id": str(child["id"]),
            "trigger": "definitive_failure",
            "from_channel": "whatsapp",
            "to_channel": "sms",
            "ordinal": 1,
        }
    ]
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")
    assert [failure["reason"] for failure in failures] == ["provider_non_retryable_failure"]
    assert _pending_dispatch_count(admin_conn, child["id"]) == 1

    async with tenant_transaction(app_session_factory, org) as session:
        prepared = await prepare_dispatch(
            session,
            organization_id=org,
            communication_task_id=child["id"],
            configured_provider_keys=(),
        )
    assert prepared.send_request is not None
    assert prepared.send_request.channel == "sms"
    assert prepared.send_request.contact_point_id == sms


def _pending_dispatch_count(conn: world.PgConnection, communication_task_id: object) -> int:
    return world.scalar(
        conn,
        """
        SELECT count(*) FROM request_engine.scheduled_actions
        WHERE owner_module = 'communications' AND action_type = 'dispatch_task'
          AND subject_kind = 'CommunicationTask' AND subject_id = %s
          AND status = 'pending'
        """,
        communication_task_id,
    )
