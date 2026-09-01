from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from request_engine.modules.communications.adapters.db.delivery_store import (
    DeliveryWorkKind,
    prepare_reconciliation,
)
from request_engine.platform.db.session import SessionFactory, tenant_transaction

from . import communication_reconcile_support as reconcile
from . import operational_support as support

pytestmark = [pytest.mark.postgres, pytest.mark.e2e]


@pytest.mark.asyncio
async def test_past_deadline_fails_task_with_durable_fact_and_skips_reconcile(
    e2e_admin_conn: support.PgConnection,
    e2e_session_factory: SessionFactory,
) -> None:
    organization_id, task_id, delivery_id = await reconcile.ambiguous_delivery(
        e2e_admin_conn,
        e2e_session_factory,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    e2e_admin_conn.execute(
        """
        UPDATE request_engine.communication_tasks
        SET expires_at = clock_timestamp() - interval '1 minute'
        WHERE id = %s
        """,
        (task_id,),
    )

    async with tenant_transaction(e2e_session_factory, organization_id) as session:
        work = await prepare_reconciliation(
            session,
            organization_id=organization_id,
            delivery_id=delivery_id,
        )

    assert work.kind is DeliveryWorkKind.SKIP
    assert work.skip_reason == "task_expired"
    assert (
        reconcile.fetch_one(
            e2e_admin_conn,
            "SELECT status FROM request_engine.communication_tasks WHERE id = %s",
            task_id,
        )
        == "failed"
    )
    assert (
        reconcile.fetch_one(
            e2e_admin_conn,
            "SELECT status FROM request_engine.communication_deliveries WHERE id = %s",
            delivery_id,
        )
        == "ambiguous"
    )
    failures = reconcile.outbox_payloads(
        e2e_admin_conn,
        organization_id,
        "communication.task_failed.v1",
    )
    assert len(failures) == 1
    assert failures[0]["communication_task_id"] == str(task_id)
    assert failures[0]["delivery_id"] == str(delivery_id)
    assert failures[0]["reason"] == "delivery_deadline_exceeded"
    assert (
        reconcile.fetch_one(
            e2e_admin_conn,
            """
        SELECT count(*)
        FROM request_engine.scheduled_actions
        WHERE owner_module = 'communications'
          AND action_type = 'reconcile_delivery'
          AND subject_id = %s
        """,
            delivery_id,
        )
        == 1
    )
