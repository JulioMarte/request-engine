"""PostgreSQL proof: a late retryable report never resurrects a failed task.

docs/v3/36 section 3 fenced finalize: a retryable outcome report arriving
after the deadline gate already closed the task (and escalated the lineage)
records evidence on the delivery row only — the task stays failed with no
pending re-arm, no retry dispatch, and no second child in the lineage.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, LiteralString

import escalation_step_actions as actions
import escalation_step_world as world
import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    finalize_provider_result,
    prepare_reconciliation,
)
from request_engine.modules.communications.contracts.delivery import (
    ProviderDeliveryResult,
    ProviderDeliveryStatus,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

pytestmark = pytest.mark.postgres


def _task_scalar(conn: world.PgConnection, query: LiteralString, task: object) -> Any:
    return world.scalar(conn, query, task)


@pytest.mark.asyncio
async def test_late_retryable_report_records_evidence_but_does_not_resurrect(
    admin_conn: world.PgConnection,
    app_session_factory: SessionFactory,
) -> None:
    org = world.new_organization(admin_conn, "late-retryable")
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
        work = await prepare_reconciliation(session, organization_id=org, delivery_id=delivery)
    assert work.kind is DeliveryWorkKind.SKIP
    assert work.skip_reason == "task_expired"
    assert len(actions.child_tasks(admin_conn, org, task)) == 1
    revision = _task_scalar(
        admin_conn,
        "SELECT revision FROM request_engine.communication_tasks WHERE id = %s",
        task,
    )
    failures = actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1")

    async with tenant_transaction(app_session_factory, org) as session:
        finalized = await finalize_provider_result(
            session,
            organization_id=org,
            delivery_id=delivery,
            result=ProviderDeliveryResult(
                status=ProviderDeliveryStatus.FAILED,
                retryable=True,
                result_data={"error_class": "provider_retryable_failure", "late": True},
            ),
        )

    assert finalized.task_terminal is True
    assert (
        _task_scalar(
            admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task,
        )
        == "failed"
    )
    assert (
        _task_scalar(
            admin_conn,
            "SELECT revision FROM request_engine.communication_tasks WHERE id = %s",
            task,
        )
        == revision
    )
    assert (
        world.scalar(
            admin_conn,
            """
            SELECT count(*) FROM request_engine.scheduled_actions
            WHERE organization_id = %s AND owner_module = 'communications'
              AND action_type = 'dispatch_task' AND subject_id = %s
            """,
            org,
            task,
        )
        == 0
    )
    assert len(actions.child_tasks(admin_conn, org, task)) == 1
    assert len(actions.ledger_rows(admin_conn, org, task)) == 1
    assert actions.outbox_payloads(admin_conn, org, "communication.task_failed.v1") == failures
    assert admin_conn.execute(
        """
        SELECT status, result_data->>'retryable', result_data->>'late'
        FROM request_engine.communication_deliveries WHERE id = %s
        """,
        (delivery,),
    ).fetchone() == ("failed", "true", "true")
